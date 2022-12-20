import os
import torch
import base64
import io
from diffusers import (
    StableDiffusionPipeline,
    StableDiffusionImg2ImgPipeline,
    StableDiffusionInpaintPipeline,
    EulerAncestralDiscreteScheduler,
    DDPMScheduler,
    DDIMScheduler,
    PNDMScheduler,
    LMSDiscreteScheduler,
    EulerDiscreteScheduler,
    DPMSolverMultistepScheduler,
    StableDiffusionPipelineSafe
)
from pytorch_lightning import seed_everything
from diffusers.pipelines.stable_diffusion import StableDiffusionSafetyChecker
from PIL import Image
from logger import logger


class SDRunner:
    _current_model = ""
    scheduler_name = "ddpm"
    do_nsfw_filter = True
    do_watermark = True
    initialized = False

    @property
    def current_model(self):
        return self._current_model

    @current_model.setter
    def current_model(self, model):
        if self._current_model != model:
            self._current_model = model
            if self.initialized:
                self.load_model()

    @property
    def model_path(self):
        model_path = self.current_model
        # if self.current_model in [
        #     "stabilityai/stable-diffusion-v1-5",
        #     "stable-diffusion-inpainting",
        #     "stabilityai/stable-diffusion-2-1-base",
        #     "stabilityai/stable-diffusion-2-inpainting",
        # ]:
        #     model_path = self.current_model
        return model_path

    def load_model(self):
        torch.cuda.empty_cache()
        # load StableDiffusionSafetyChecker with CLIPConfig
        self.safety_checker = StableDiffusionSafetyChecker(
            StableDiffusionSafetyChecker.config_class()
        )
        #self.feature_extractor = CLIPFeatureExtractor()

        # check if self.current_model has ckpt extension
        # if self.current_model.endswith(".ckpt"):
        #     print("found checkpoint file")
        #     self.current_model = "/home/joe/Projects/ai/runai2/stablediffusion/stable-diffusion-v1-5"
        # self.current_model = "/home/joe/Projects/ai/runai2/models/stable-diffusion-v1-5"

        if self.do_nsfw_filter:
            self.txt2img = StableDiffusionPipelineSafe.from_pretrained(
                self.model_path,
                torch_dtype=torch.half,
                scheduler=self.scheduler,
                low_cpu_mem_usage=True,
                # safety_checker=self.safety_checker,
                # feature_extractor=self.feature_extractor,
                # revision="fp16"
            )
        else:
            self.txt2img = StableDiffusionPipeline.from_pretrained(
                self.model_path,
                torch_dtype=torch.half,
                scheduler=self.scheduler,
                low_cpu_mem_usage=True,
                safety_checker=None,
            )
        self.txt2img.enable_xformers_memory_efficient_attention()
        self.txt2img.to("cuda")
        self.img2img = StableDiffusionImg2ImgPipeline(**self.txt2img.components)
        self.inpaint = StableDiffusionInpaintPipeline(**self.txt2img.components)

    schedulers = {
        "ddpm": DDPMScheduler,
        "ddim": DDIMScheduler,
        "plms": PNDMScheduler,
        "lms": LMSDiscreteScheduler,
        "euler_a": EulerAncestralDiscreteScheduler,
        "euler": EulerDiscreteScheduler,
        "dpm": DPMSolverMultistepScheduler,
    }

    registered_schedulers = {}

    @property
    def scheduler(self):
        if not self.model_path or self.model_path == "":
            raise Exception("Chicken / egg problem, model path not set")
        if self.scheduler_name in self.schedulers:
            if self.scheduler_name not in self.registered_schedulers:
                self.registered_schedulers[self.scheduler_name] = self.schedulers[self.scheduler_name].from_pretrained(
                    self.model_path,
                    subfolder="scheduler"
                )
            return self.registered_schedulers[self.scheduler_name]
        else:
            raise ValueError("Invalid scheduler name")

    def change_scheduler(self):
        if self.model_path and self.model_path != "":
            self.txt2img.scheduler = self.scheduler
            self.img2img.scheduler = self.scheduler
            self.inpaint.scheduler = self.scheduler


    def generator_sample(self, data, image_handler):
        self.image_handler = image_handler
        return self.generate(data)

    def convert(self, model):
        # get location of .ckpt file
        model_path = model.replace(".ckpt", "")
        model_name = model_path.split("/")[-1]

        required_files = [
            "feature_extractor/preprocessor_config.json",
            "safety_checker/config.json",
            "safety_checker/pytorch_model.bin",
            "scheduler/scheduler_config.json",
            "text_encoder/config.json",
            "text_encoder/pytorch_model.bin",
            "tokenizer/merges.txt",
            "tokenizer/vocab.json",
            "tokenizer/tokenizer_config.json",
            "tokenizer/special_tokens_map.json",
            "unet/config.json",
            "unet/diffusion_pytorch_model.bin",
            "vae/config.json",
            "vae/diffusion_pytorch_model.bin",
            "model_index.json",
        ]

        missing_files = False
        for required_file in required_files:
            if not os.path.isfile(f"{model_path}/{required_file}"):
                logger.warning(f"missing file {model_path}/{required_file}")
                missing_files = True
                break

        if missing_files:
            dump_path = f"./models/stablediffusion/{model_name}"
            version = "v1-5"
            from scripts.convert import convert
            logger.info("Converting model")
            convert(
                extract_ema=True,
                checkpoint_path=model,
                dump_path=model_path,
                original_config_file=f"./models/stable-diffusion-{version}/v1-inference.yaml",
            )
            logger.info("ckpt converted to diffusers")
        return model_path

    def initialize(self):
        self.load_model()
        self.initialized = True

    def generate(self, data):
        options = data["options"]

        # Get the other values from options
        action = data.get("action", "txt2img")

        scheduler_name = options.get(f"{action}_scheduler", "ddpm")
        if self.scheduler_name != scheduler_name:
            self.scheduler_name = scheduler_name
            self.change_scheduler()
        #
        # # get model and switch to it
        model = options.get(f"{action}_model", self.current_model)

        print("MODEL REQUESTED: ", model)

        # if model is ckpt
        if model.endswith(".ckpt"):
            model = self.convert(model)

        if action in ["inpaint", "outpaint"]:
            if model in [
                "stabilityai/stable-diffusion-2-1-base",
                "stabilityai/stable-diffusion-2-base"
            ]:
                model = "stabilityai/stable-diffusion-2-inpainting"
            else:
                model = "stabilityai/stable-diffusion-inpainting"

        if model != self.current_model:
            self.current_model = model

        if not self.initialized:
            self.initialize()

        seed = int(options.get(f"{action}_seed", 42))
        guidance_scale = float(options.get(f"{action}_scale", 7.5))
        num_inference_steps = int(options.get(f"{action}_ddim_steps", 50))
        self.num_inference_steps = num_inference_steps
        self.strength = float(options.get(f"{action}_strength", 1.0))

        do_nsfw_filter = bool(options.get(f"do_nsfw_filter", False))
        do_watermark = bool(options.get(f"do_watermark", False))
        enable_community_models = bool(options.get(f"enable_community_models", False))
        if do_nsfw_filter != self.do_nsfw_filter:
            self.do_nsfw_filter = do_nsfw_filter
            self.load_model()
        if do_watermark != self.do_watermark:
            self.do_watermark = do_watermark
            self.load_model()
        prompt = options.get(f"{action}_prompt", "")
        negative_prompt = options.get(f"{action}_negative_prompt", "")
        C = int(options.get(f"{action}_C", 4))
        f = int(options.get(f"{action}_f", 8))
        batch_size = int(data.get(f"{action}_n_samples", 1))

        # sample the model
        with torch.no_grad() as _torch_nograd, \
            torch.cuda.amp.autocast() as _torch_autocast:
            try:
                # clear cuda cache
                for n in range(0, batch_size):
                    seed = seed + n
                    print("GETTING READY TO SEED WITH ", seed)
                    seed_everything(seed)
                    image = None
                    if action == "txt2img":
                        image = self.txt2img(
                            prompt,
                            negative_prompt=negative_prompt,
                            guidance_scale=guidance_scale,
                            num_inference_steps=num_inference_steps,
                            callback=self.callback
                        ).images[0]
                    elif action == "img2img":
                        bytes = base64.b64decode(data["options"]["pixels"])
                        image = Image.open(io.BytesIO(bytes))
                        image = self.img2img(
                            prompt=prompt,
                            negative_prompt=negative_prompt,
                            image=image.convert("RGB"),
                            strength=self.strength,
                            guidance_scale=guidance_scale,
                            num_inference_steps=num_inference_steps,
                            callback=self.callback
                        ).images[0]
                        pass
                    elif action in ["inpaint", "outpaint"]:
                        bytes = base64.b64decode(data["options"]["pixels"])
                        mask_bytes = base64.b64decode(data["options"]["mask"])

                        image = Image.open(io.BytesIO(bytes))
                        mask = Image.open(io.BytesIO(mask_bytes))

                        # convert mask to 1 channel
                        # print mask shape
                        image = self.inpaint(
                            prompt=prompt,
                            negative_prompt=negative_prompt,
                            image=image,
                            mask_image=mask,
                            guidance_scale=guidance_scale,
                            num_inference_steps=num_inference_steps,
                            callback=self.callback
                        ).images[0]
                        pass

                    # use pillow to convert the image to a byte array
                    if image:
                        img_byte_arr = io.BytesIO()
                        image.save(img_byte_arr, format='PNG')
                        img_byte_arr = img_byte_arr.getvalue()
                        #return flask.Response(img_byte_arr, mimetype='image/png')
                        self.image_handler(img_byte_arr, data)
            except TypeError as e:
                if action in ["inpaint", "outpaint"]:
                    print(f"ERROR IN {action}")
                print(e)
            # except Exception as e:
            #     print("Error during generation 1")
            #     print(e)
            #     #return flask.jsonify({"error": str(e)})

    def callback(self, step, time_step, latents):
        self.tqdm_callback(step, int(self.num_inference_steps * self.strength))

    def __init__(self, *args, **kwargs):
        self.tqdm_callback = kwargs.get("tqdm_callback", None)
        super().__init__(*args)