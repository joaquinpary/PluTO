import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("coord_transform_main")

def main():
    logger.info("Starting coordinates transformation engine...")
    # TODO: Inicializar conexión MQTT y mantener loop

if __name__ == "__main__":
    main()
