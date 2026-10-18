import os
import logging
import colorlog
import inspect

logger = logging.getLogger(__name__)

def setupLogging():
    """Set up logging with colors."""
    rootLogger = logging.getLogger()

    if rootLogger.handlers:
        caller_info = inspect.stack()[1]
        caller_file = caller_info.filename
        caller_line = caller_info.lineno
        caller_function = caller_info.function
        logger.warning(f"root logger setup once from {caller_file}:{caller_line} in {caller_function} — basic config or rootlogger called before setupLogging().")

    log_level = getattr(logging, os.getenv('LOG_LEVEL', 'INFO').upper(), logging.INFO)

    logging.basicConfig(
        level=log_level,
        format="%(log_color)s%(asctime)s %(name)s[%(levelname)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler()],
        style="%",
        force=True # needs to be forced otherwise any call to logging.log will setup a root logger and this will be ignored
    )

    # override the formater to use colors
    rootLogger.handlers[0].setFormatter(
        colorlog.ColoredFormatter(
            "%(log_color)s%(asctime)s %(name)s[%(levelname)s]: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            log_colors={
                'DEBUG': 'cyan',
                'INFO': 'green',
                'WARNING': 'yellow',
                'ERROR': 'red',
                'CRITICAL': 'bold_red',
            }
        )
    )

    module_levels = os.getenv("MODULE_LOG_LEVELS", "")
    if module_levels:
        for item in module_levels.split(","):
            if not "=" in item:
                continue
            
            module_name, level_name = item.split("=", 1)
            level = getattr(logging, level_name.strip().upper(), None)
            if isinstance(level, int):
                logging.getLogger(module_name.strip()).setLevel(level)

    logger.debug("Finished setting up logger")