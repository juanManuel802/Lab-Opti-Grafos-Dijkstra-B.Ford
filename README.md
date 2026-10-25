# Instalación en Linux

El proyecto usa tres dependencias externas: **PySide6**, **graph-tool** y **Pycairo**. PySide6 se instala con `pip`; graph-tool y Pycairo deben instalarse mediante el gestor de paquetes de la distribución para que queden vinculados a las bibliotecas nativas del sistema.

> Se necesita Python 3.10 o posterior. Instala graph-tool antes de crear el entorno virtual. El entorno se crea con acceso a los paquetes del sistema para poder importar graph-tool y Pycairo desde él.

## Fedora

1. Instala Python, el soporte para entornos virtuales y las bibliotecas nativas:

   ```bash
   sudo dnf install python3 python3-pip python3-virtualenv python3-graph-tool python3-cairo
   ```

2. Entra a la carpeta del proyecto y crea el entorno virtual con acceso a los paquetes del sistema:

   ```bash
   cd /ruta/a/Grafos
   python3 -m venv --system-site-packages .venv
   ```

3. Actívalo e instala las dependencias Python del archivo `requirements.txt`:

   ```bash
   source .venv/bin/activate
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   ```

4. Inicia el visualizador:

   ```bash
   python visualizador_grafos.py
   ```

## Ubuntu y Debian

1. Instala Python, el módulo `venv` y los paquetes del sistema para graph-tool y Cairo:

   ```bash
   sudo apt update
   sudo apt install python3 python3-venv python3-pip python3-graph-tool python3-cairo
   ```

   Si tu versión de Ubuntu o Debian no ofrece `python3-graph-tool`, consulta las [instrucciones oficiales de instalación de graph-tool](https://graph-tool.skewed.de/installation.html) para configurar el repositorio correspondiente a tu versión.

2. Entra a la carpeta del proyecto y crea el entorno virtual con acceso a los paquetes del sistema:

   ```bash
   cd /ruta/a/Grafos
   python3 -m venv --system-site-packages .venv
   ```

3. Actívalo e instala PySide6 y el resto de dependencias declaradas:

   ```bash
   source .venv/bin/activate
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   ```

4. Inicia el visualizador:

   ```bash
   python visualizador_grafos.py
   ```

## Otras distribuciones

Instala `graph-tool` y Pycairo con el gestor de paquetes de tu distribución antes de crear el entorno virtual. Los nombres habituales son `python-graph-tool` y `python-cairo` en Arch Linux. La [página oficial de instalación de graph-tool](https://graph-tool.skewed.de/installation.html) contiene instrucciones actualizadas para Fedora, Arch, Debian, Ubuntu y otras opciones.

Después crea y activa el entorno virtual. En los comandos siguientes, sustituye `python3` por el intérprete asociado a los paquetes `graph-tool` y Pycairo que instalaste:

```bash
cd /ruta/a/Grafos
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python visualizador_grafos.py
```

## ¿Por qué `--system-site-packages`?

`graph-tool` contiene extensiones compiladas y normalmente se distribuye como paquete del sistema, no como un paquete pip común. La opción `--system-site-packages` permite que el entorno virtual encuentre ese paquete y Pycairo, mientras mantiene PySide6 instalado dentro de `.venv`. Crea el entorno virtual **después** de instalar `graph-tool`; si ya existía, elimínalo y créalo de nuevo para que herede los paquetes del sistema.

## Comprobación

Con `.venv` activado, comprueba que se puedan importar las tres dependencias:

```bash
python -c "import PySide6, cairo, graph_tool; print('PySide6', PySide6.__version__); print('graph-tool', graph_tool.__version__); print('Pycairo', cairo.version)"
```

Si aparece `ModuleNotFoundError: graph_tool` o `ModuleNotFoundError: cairo`, revisa que instalaste los paquetes del sistema y que creaste el entorno con `--system-site-packages` usando el mismo Python del sistema.

Si la ventana no abre y Qt informa que no puede cargar el plugin de plataforma `xcb`, instala las bibliotecas XCB que indique el mensaje de error usando el gestor de paquetes de tu distribución. Los nombres concretos dependen de la distribución y de su versión de Qt.

## Windows

graph-tool no ofrece una instalación nativa convencional para Windows; su documentación recomienda usar [Windows Subsystem for Linux (WSL)](https://graph-tool.skewed.de/installation.html). Estos pasos de Linux también aplican dentro de una distribución WSL. El entorno y las dependencias de WSL se instalan por separado de Python en Windows.
