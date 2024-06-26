import threading
from runai import settings
from typing import Optional
from runai.logger import logger


class Connection:
    """
    Base connection class.
    """
    threads = []

    def start_thread(
            self, target: Optional, daemon: bool = False, name: str = None
    ):
        """
        Start a thread and append it to the list of threads on this object.
        :param target: func, thread will run this function
        :param daemon: boolean, whether the thread is a daemon thread
        :param name: str, name of the thread
        return: thread
        """
        thread = threading.Thread(target=target, daemon=daemon)

        if name:
            thread.name = name
        thread.start()
        self.threads.append(thread)
        return thread

    def connect(self):
        """
        Override this method to set up a connection to something.

        Do not call connect directly, it should be used in a thread.

        Use the start() method which starts this method in a new thread.
        :return: None
        """

    def disconnect(self):
        """
        Override this method to disconnect from something.
        :return: None
        """

    def reconnect(self):
        """
        Disconnects then reconnects to service. Does not stop the thread.
        :return: None
        """
        self.disconnect()
        self.connect()

    def start(self):
        """
        Starts a new thread with a connection to service.
        :return: None
        """
        self.start_thread(
            target=self.connect,
            name="Connection thread"
        )

    def stop(self):
        """
        Disconnects from service and stops the thread
        :return: None
        """
        self.disconnect()
        logger.info("Stopping connection thread...")
        for index, thread in enumerate(self.threads):
            total = len(self.threads)
            name = thread.name
            logger.info(f"{index+1} of {total} Stopping thread {name}")
            try:
                thread.join()
            except RuntimeError:
                logger.info(f"Thread {thread.name} not running")
            logger.info(f"Stopped thread {thread.name}...")
        logger.info("All threads stopped")

    def __init__(self, *args, **kwargs):
        self.port = kwargs.get("port", settings.DEFAULT_PORT)
        self.host = kwargs.get("host", settings.DEFAULT_HOST)
        self.do_timeout = kwargs.get("do_timeout", False)
        self.packet_size = kwargs.get("packet_size", settings.PACKET_SIZE)
        self.max_client_connections = kwargs.get("max_client_connections", 1)
        self.model_base_path = kwargs.get("model_base_path", ".")

        self.start()
