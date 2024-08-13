import json
import re
from datetime import datetime

from runai.agent import Agent
from runai.llm_request import LLMRequest
from runai.settings import DEFAULT_HOST, DEFAULT_PORT, PACKET_SIZE, USER_NAME, BOT_NAME, LLM_INSTRUCTIONS
from runai.socket_client import SocketClient


class Client:
    def __init__(
        self,
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
        packet_size=PACKET_SIZE,
        user_name=USER_NAME,
        bot_name=BOT_NAME
    ):
        self.host = host
        self.port = port
        self.packet_size = packet_size
        self.socket_client = self.connect_socket()
        self.bot_agent = Agent(name=bot_name)
        self.user_agent = Agent(name=user_name)

        self.history = []

    def connect_socket(self):
        socket_client = SocketClient(host=self.host, port=self.port, packet_size=self.packet_size)
        socket_client.connect()
        return socket_client

    @property
    def dialogue_instructions(self):
        return LLM_INSTRUCTIONS["dialogue_instructions"].format(
            dialogue_rules=self.dialogue_rules,
            mood_stats=self.mood_stats,
            contextual_information=self.contextual_information
        )

    @property
    def contextual_information(self):
        return LLM_INSTRUCTIONS["contextual_information"].format(
            date_time=datetime.now().strftime("%m/%d/%Y, %I:%M:%S %p"),
            weather="sunny"
        )

    @property
    def update_mood_instructions(self):
        return LLM_INSTRUCTIONS["update_mood_instructions"].format(
            speaker_name=self.bot_agent.name,
            python_rules=self.python_rules
        )

    @property
    def mood_stats(self):
        stats = ", ".join([f"{k}: {v}" for k, v in self.bot_agent.mood_stats.items()])
        return (
            f"{self.bot_agent.name}'s mood stats:\n"
            f"{stats}\n"
        )

    @property
    def dialogue_rules(self):
        return LLM_INSTRUCTIONS["dialogue_rules"].format(
            speaker_name=self.bot_agent.name,
            listener_name=self.user_agent.name
        )

    @property
    def json_rules(self):
        return LLM_INSTRUCTIONS["json_rules"]

    @property
    def python_rules(self):
        return LLM_INSTRUCTIONS["python_rules"]

    def do_greeting(self):
        return self.do_query(
            LLM_INSTRUCTIONS["greeting_prompt"].format(speaker_name=self.bot_agent.name),
            self.dialogue_instructions
        )

    def do_response(self):
        return self.do_query(
            LLM_INSTRUCTIONS["response_prompt"].format(speaker_name=self.bot_agent.name),
            self.dialogue_instructions
        )

    def update_mood(self, agent: Agent):
        stats = ", ".join([f'"{k}": {v}' for k, v in agent.mood_stats.items()])
        res = self.do_query(
            LLM_INSTRUCTIONS["update_mood_prompt"].format(
                agent_name=agent.name,
                stats=stats
            ),
            self.update_mood_instructions
        )
        python_code_match = self.find_python(res)
        if python_code_match:
            python_code = python_code_match.group(1)
            exec(python_code, {}, {"agent": agent})
        return agent

    @staticmethod
    def find_python(res: str):
        return Client.find_code_block("python", res)

    @staticmethod
    def find_json(res: str):
        return Client.find_code_block("json", res)

    @staticmethod
    def find_code_block(language: str, res: str) -> re.Match:
        return re.search(r'```' + language + 'r\n(.*?)\n```', res, re.DOTALL)

    def do_prompt(self, user_prompt, update_speaker_mood=False):
        self.update_history(self.user_agent.name, user_prompt)

        if update_speaker_mood:
            self.bot_agent = self.update_mood(self.bot_agent)

        for res in self.do_response():
            yield res

        return ""

    def update_history(self, name: str, message: str):
        self.history.append({
            "name": name,
            "message": message
        })

    def do_query(self, user_prompt, instructions):
        llm_request = LLMRequest(
            history=self.history,
            speaker=self.bot_agent,
            listener=self.user_agent,
            use_usernames=True,
            prompt_prefix="",
            instructions=instructions,
            prompt=user_prompt
        )
        self.socket_client.send_message(json.dumps(llm_request.to_dict()))

        server_response = ""
        for res in self.socket_client.receive_message():
            res.replace(f"{self.bot_agent.name}: ", "")
            server_response += res.replace('\x00', '')
            yield server_response
        return server_response.replace('\x00', '')

    def _handle_prompt(self, prompt: str):
        response = ""
        for txt in self.do_prompt(prompt):
            response = str(txt)
            yield response

        self.history.append({
            "name": self.bot_agent.name,
            "message": response
        })

    def run(self):
        while True:
            prompt = input("Enter a prompt: ")
            for res in self._handle_prompt(prompt):
                self.handle_res(res)

    def handle_res(self, res):
        print(res)


if __name__ == "__main__":
    client = Client()
    client.run()
