import json
from bot.utils import logger


def read_or_create_config_file(relative_path: str) -> dict:
    """Reads the contents of a config file. If the file does not exist, creates it.

     Args:
       relative_path: Path to the .json file.

     Returns:
       The contents of the file, or an empty dict if the file was  empty or created.
     """
    try:
        with open(relative_path, 'r') as f:
            content = f.read()
            config = json.loads(content) if content else {}
    except FileNotFoundError:
        config = {}
        with open(relative_path, 'w'):
            print(f"Accounts config file `{relative_path}` not found. Creating a new one.")
    return config


def write_config_file(relative_path: str, content: dict):
    """Writes the contents of a config file. If the file does not exist, creates it.

     Args:
       relative_path: Path to the .json file.
       content (dict): Content we want to write

     Returns:
       The contents of the file, or an empty dict if the file was  empty or created.
     """
    try:
        with open(relative_path, 'w+') as f:
            json.dump(content, f, indent=2)
    except IOError as e:
        logger.error(f"An error occurred while writing to {relative_path}: {e}")
