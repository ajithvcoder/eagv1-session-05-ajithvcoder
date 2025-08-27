import logging
import os 

os.makedirs("logs", exist_ok=True)

# Create and configure logger
logging.basicConfig(filename="logs/mcp_server.log",
                    format='%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(funcName)s() - %(message)s',
                    filemode='a')

# Creating an object
mcp_server_logger = logging.getLogger()

# Setting the threshold of logger to DEBUG
mcp_server_logger.setLevel(logging.DEBUG)


# Create and configure logger
logging.basicConfig(filename="logs/client.log",
                    format='%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(funcName)s() - %(message)s',
                    filemode='a')

# Creating an object
client_logger = logging.getLogger()

# Setting the threshold of logger to DEBUG
client_logger.setLevel(logging.DEBUG)

