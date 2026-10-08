from __future__ import annotations

import random
import re
import sys
from dataclasses import dataclass
from io import BytesIO
from time import perf_counter
from typing import Hashable, Iterator

import cairo
from graph_tool import Graph
from graph_tool.draw import graph_draw, sfdp_layout
from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtSvgWidgets import QGraphicsSvgItem
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFormLayout,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSplitter,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

# Modelo del grafo
Nodo = Hashable
Peso = int | float | None


@dataclass
class PasoRuta:
    distancias: dict[Nodo, int | float]
    previos: dict[Nodo, Nodo | None]
    destacados: set[Nodo]


@dataclass
class ResultadoRuta:
    distancia: int | float
    ruta: list[Nodo]
    pasos: list[PasoRuta]
    estado: str
    ciclo_negativo: bool
    intentos: int
    mejoras: int
    tiempo: float


@dataclass
class Grafo:
    nodos: list[Nodo]
    dirigido: bool = False
    ponderado: bool = False

    def __post_init__(self) -> None:
        if len(set(self.nodos)) != len(self.nodos):
            raise ValueError("Los nodos deben ser únicos.")
        self._adyacencias: dict[Nodo, dict[Nodo, Peso]] = {
            nodo: {} for nodo in self.nodos
        }

    def agregar_arista(self, origen: Nodo, destino: Nodo, peso: Peso = None) -> None:
        if origen not in self._adyacencias or destino not in self._adyacencias:
            raise ValueError("El origen y el destino deben pertenecer al grafo.")
        if self.ponderado:
            if peso is None or peso == 0:
                raise ValueError("El peso debe ser distinto de cero.")
        else:
            peso = None
        self._adyacencias[origen][destino] = peso
        if not self.dirigido:
            self._adyacencias[destino][origen] = peso

    def eliminar_arista(self, origen: Nodo, destino: Nodo) -> None:
        self._adyacencias[origen].pop(destino, None)
        if not self.dirigido:
            self._adyacencias[destino].pop(origen, None)

    def existe_arista(self, origen: Nodo, destino: Nodo) -> bool:
        return destino in self._adyacencias[origen]

    def peso_arista(self, origen: Nodo, destino: Nodo) -> Peso:
        return self._adyacencias[origen].get(destino)

    def adyacentes(self, nodo: Nodo) -> dict[Nodo, Peso]:
        return self._adyacencias[nodo].copy()

    def aristas(self) -> Iterator[tuple[Nodo, Nodo, Peso]]:
        indices = {nodo: i for i, nodo in enumerate(self.nodos)}
        for origen in self.nodos:
            for destino, peso in self._adyacencias[origen].items():
                if self.dirigido or indices[origen] <= indices[destino]:
                    yield origen, destino, peso

    def tiene_pesos_negativos(self) -> bool:
        return any(peso is not None and peso < 0
                   for vecinos in self._adyacencias.values()
                   for peso in vecinos.values())

    def _inicio_ruta(self, origen: Nodo) -> tuple[dict, dict, list[PasoRuta]]:
        distancias = {nodo: float("inf") for nodo in self.nodos}
        previos = {nodo: None for nodo in self.nodos}
        distancias[origen] = 0
        pasos = [PasoRuta(distancias.copy(), previos.copy(), set())]
        return distancias, previos, pasos

    def _dijkstra(self, origen: Nodo) -> tuple[dict, dict, list[PasoRuta], int, int]:
        if self.tiene_pesos_negativos():
            raise ValueError("Dijkstra no admite pesos negativos.")
        distancias, previos, pasos = self._inicio_ruta(origen)
        pendientes = list(self.nodos)
        intentos = mejoras = 0
        while pendientes:
            actual = min(pendientes, key=distancias.get)
            if distancias[actual] == float("inf"):
                break
            pendientes.remove(actual)
            for vecino, peso in self._adyacencias[actual].items():
                intentos += 1
                nueva = distancias[actual] + (1 if peso is None else peso)
                if nueva < distancias[vecino]:
                    distancias[vecino] = nueva
                    previos[vecino] = actual
                    mejoras += 1
            pasos.append(PasoRuta(distancias.copy(), previos.copy(), {actual}))
        return distancias, previos, pasos, intentos, mejoras

    def dijkstra(self, origen: Nodo) -> tuple[dict, dict]:
        distancias, previos, _, _, _ = self._dijkstra(origen)
        return distancias, previos

    def _bellman_ford(self, origen: Nodo) -> tuple[dict, dict, list[PasoRuta], bool, set[Nodo], int, int]:
        distancias, previos, pasos = self._inicio_ruta(origen)
        aristas = [(inicio, fin, 1 if peso is None else peso)
                   for inicio in self.nodos
                   for fin, peso in self._adyacencias[inicio].items()]
        intentos = mejoras = 0
        for _ in range(len(self.nodos) - 1):
            cambiados = set()
            for inicio, fin, peso in aristas:
                intentos += 1
                if distancias[inicio] != float("inf") and distancias[inicio] + peso < distancias[fin]:
                    distancias[fin] = distancias[inicio] + peso
                    previos[fin] = inicio
                    cambiados.add(fin)
                    mejoras += 1
            pasos.append(PasoRuta(distancias.copy(), previos.copy(), cambiados))
        afectados = set()
        for inicio, fin, peso in aristas:
            intentos += 1
            if distancias[inicio] != float("inf") and distancias[inicio] + peso < distancias[fin]:
                afectados.add(fin)
        hay_ciclo = bool(afectados)
        pendientes = list(afectados)
        while pendientes:
            actual = pendientes.pop()
            for vecino in self._adyacencias[actual]:
                if vecino not in afectados:
                    afectados.add(vecino)
                    pendientes.append(vecino)
        return distancias, previos, pasos, hay_ciclo, afectados, intentos, mejoras

    def bellman_ford(self, origen: Nodo) -> tuple[dict, dict, bool]:
        distancias, previos, _, ciclo, _, _, _ = self._bellman_ford(origen)
        return distancias, previos, ciclo

    def calcular_ruta(self, origen: Nodo, destino: Nodo, algoritmo: str) -> ResultadoRuta:
        if origen not in self._adyacencias or destino not in self._adyacencias:
            raise ValueError("El origen y el destino deben pertenecer al grafo.")
        inicio = perf_counter()
        ciclo = False
        afectados: set[Nodo] = set()
        if algoritmo == "Dijkstra":
            distancias, previos, pasos, intentos, mejoras = self._dijkstra(origen)
        elif algoritmo == "Bellman-Ford":
            distancias, previos, pasos, ciclo, afectados, intentos, mejoras = self._bellman_ford(origen)
        else:
            raise ValueError("Algoritmo desconocido.")
        if destino in afectados:
            estado, ruta = "ciclo_negativo", []
        elif distancias[destino] == float("inf"):
            estado, ruta = "sin_ruta", []
        else:
            estado, ruta = "ruta", []
            actual = destino
            while actual is not None:
                ruta.append(actual)
                actual = previos[actual]
            ruta.reverse()
        distancia = float("-inf") if estado == "ciclo_negativo" else distancias[destino]
        return ResultadoRuta(distancia, ruta, pasos, estado, ciclo,
                             intentos, mejoras, perf_counter() - inicio)

    def ruta_mas_corta(self, origen: Nodo, destino: Nodo) -> tuple[float, list[Nodo]]:
        resultado = self.calcular_ruta(origen, destino, "Dijkstra")
        return resultado.distancia, resultado.ruta


# Matriz de adyacencia

def identificadores(cantidad: int, tipo: str) -> list[str]:
    if tipo == "Números":
        return [str(i) for i in range(1, cantidad + 1)]
    letras: list[str] = []
    for indice in range(cantidad):
        n = indice
        etiqueta = ""
        while True:
            n, resto = divmod(n, 26)
            etiqueta = chr(ord("A") + resto) + etiqueta
            if n == 0:
                break
            n -= 1
        letras.append(etiqueta)
    return letras


def interpretar_valor(texto: str, ponderado: bool) -> tuple[bool, int | float | None]:
    valor = texto.strip()
    if valor == "" or valor == "0":
        return False, None
    if ponderado:
        if not re.fullmatch(r"-?(?:\d+(?:\.\d*)?|\.\d+)", valor):
            raise ValueError("Ingrese un peso numérico o deje la celda vacía.")
        peso = float(valor) if "." in valor else int(valor)
        if peso == 0:
            raise ValueError("El peso debe ser distinto de cero.")
        return True, peso
    if valor.upper() == "T":
        return True, None
    raise ValueError("Use T para una arista, o deje la celda vacía.")


class MatrizAdyacencia(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.tabla = QTableWidget()
        self.tabla.setAlternatingRowColors(True)
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.AllEditTriggers)
        self.tabla.horizontalHeader().setDefaultSectionSize(78)
        self.tabla.verticalHeader().setDefaultSectionSize(38)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(18)
        layout.addWidget(self.tabla, 1, Qt.AlignmentFlag.AlignHCenter)
        self.graficar_btn = QPushButton("Graficar")
        layout.addWidget(self.graficar_btn)
        self.grafo: Grafo | None = None
        self.etiquetas: list[str] = []
        self._sincronizando = False
        self.on_error = None
        self.on_graficar = None
        self.graficar_btn.clicked.connect(self._solicitar_grafico)
        self.tabla.itemChanged.connect(self._celda_cambiada)

    def preparar(self, grafo: Grafo, editable: bool = True) -> None:
        self.grafo = grafo
        self.etiquetas = [str(n) for n in grafo.nodos]
        self.tabla.blockSignals(True)
        self.tabla.clear()
        self.tabla.setRowCount(len(self.etiquetas))
        self.tabla.setColumnCount(len(self.etiquetas))
        self.tabla.setFixedWidth(min(850, max(480, len(self.etiquetas) * 78 + 66)))
        self.tabla.setHorizontalHeaderLabels(self.etiquetas)
        self.tabla.setVerticalHeaderLabels(self.etiquetas)
        self.tabla.setEditTriggers(
            QAbstractItemView.EditTrigger.AllEditTriggers if editable
            else QAbstractItemView.EditTrigger.NoEditTriggers
        )
        for i, origen in enumerate(grafo.nodos):
            for j, destino in enumerate(grafo.nodos):
                peso = grafo.peso_arista(origen, destino)
                texto = ("T" if not grafo.ponderado else str(peso)) if grafo.existe_arista(origen, destino) else ""
                self.tabla.setItem(i, j, QTableWidgetItem(texto))
        self.tabla.blockSignals(False)

    def _solicitar_grafico(self) -> None:
        if self.on_graficar is not None:
            self.on_graficar()

    def _celda_cambiada(self, item: QTableWidgetItem) -> None:
        if self._sincronizando or self.grafo is None:
            return
        fila, columna = item.row(), item.column()
        origen, destino = self.grafo.nodos[fila], self.grafo.nodos[columna]
        anterior = self.grafo.existe_arista(origen, destino)
        anterior_peso = self.grafo.peso_arista(origen, destino)
        try:
            existe, peso = interpretar_valor(item.text(), self.grafo.ponderado)
        except ValueError as error:
            self._sincronizando = True
            item.setText(("T" if not self.grafo.ponderado else str(anterior_peso)) if anterior else "")
            self._sincronizando = False
            if self.on_error:
                self.on_error(str(error))
            return
        if existe:
            self.grafo.agregar_arista(origen, destino, peso)
        else:
            self.grafo.eliminar_arista(origen, destino)
        if not self.grafo.dirigido:
            self._sincronizando = True
            espejo = self.tabla.item(columna, fila)
            if espejo is not None:
                espejo.setText(item.text())
            self._sincronizando = False
        if self.on_error:
            self.on_error("")


# Visualización del grafo
class VisualizadorGrafo(QGraphicsView):
    nodo_pulsado = Signal(str)

    COLOR_NODO = "#174A63"
    FONDO_NODO = "#E4F3F3"
    COLOR_ARISTA = "#8296A7"
    COLOR_ARISTA_DENSA = "#8296A766"
    COLOR_SELECCION = "#D78157"
    TAMANO_NODO = 30
    TAMANO_NODO_GRANDE = 20
    TAMANO_TEXTO = 12
    TAMANO_PESO = 10
    GROSOR_ARISTA = 1.5
    LIMITE_ETIQUETAS_PESO = 70
    LIMITE_ARISTAS_DENSAS = 160
    FRACCION_VISTA_GRANDE = 0.88
    FRACCION_VISTA_CON_BUCLES = 0.82
    EXPONENTE_REPULSION_GRANDE = 3.0

    def __init__(self) -> None:
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
        )
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setMouseTracking(True)
        self.setBackgroundBrush(QColor("#FFFFFF"))
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self._escala = 1.0
        self._nodos_ruta: set[int] = set()
        self._aristas_ruta: set[tuple[int, int]] = set()
        self._dirigido = False
        self._seleccion_habilitada = False
        self._visual: Graph | None = None
        self._posiciones = None
        self._nombres = None
        self._pesos = None
        self._identificadores: list[str] = []
        self._puntos: list[QPointF] = []
        self._renderer: QSvgRenderer | None = None
        self._mapa_pesos: QImage | None = None
        self._peso_por_color: dict[int, str] = {}

    def mostrar(self, grafo: Grafo) -> None:
        visual = Graph(directed=grafo.dirigido)
        visual.add_vertex(len(grafo.nodos))
        indices = {nodo: indice for indice, nodo in enumerate(grafo.nodos)}
        nombres = visual.new_vertex_property("string")
        pesos = visual.new_edge_property("string") if grafo.ponderado else None
        for nodo, indice in indices.items():
            nombres[visual.vertex(indice)] = str(nodo)
        for origen, destino, peso in grafo.aristas():
            arista = visual.add_edge(indices[origen], indices[destino])
            if pesos is not None:
                pesos[arista] = str(peso)
        self._visual = visual
        if visual.num_vertices() > 24:
            self._posiciones = sfdp_layout(visual, p=self.EXPONENTE_REPULSION_GRANDE)
        else:
            self._posiciones = sfdp_layout(visual)
        self._nombres = nombres
        self._pesos = pesos
        self._identificadores = [str(nodo) for nodo in grafo.nodos]
        self._dirigido = grafo.dirigido
        self._seleccion_habilitada = grafo.ponderado
        self._nodos_ruta.clear()
        self._aristas_ruta.clear()
        self._mapa_pesos = None
        self._peso_por_color.clear()
        self._dibujar()
        self.encuadrar()

    def resaltar_ruta(self, ruta: list[Nodo]) -> None:
        indices = {nombre: indice for indice, nombre in enumerate(self._identificadores)}
        recorrido = [indices[str(nodo)] for nodo in ruta]
        self._nodos_ruta = set(recorrido)
        self._aristas_ruta = {
            (a, b) if self._dirigido else tuple(sorted((a, b)))
            for a, b in zip(recorrido, recorrido[1:])
        }
        if self._visual is not None:
            self._dibujar()

    def _dibujar(self) -> None:
        visual = self._visual
        if visual is None:
            return
        ancho = max(1, self.viewport().width())
        alto = max(1, self.viewport().height())
        posiciones = [self._posiciones[visual.vertex(i)] for i in range(visual.num_vertices())]
        grande = visual.num_vertices() > 24
        denso = visual.num_edges() > self.LIMITE_ARISTAS_DENSAS
        tamano_nodo = self.TAMANO_NODO_GRANDE if grande else self.TAMANO_NODO
        tamano_texto = 10 if grande else self.TAMANO_TEXTO
        xs = [p[0] for p in posiciones]
        ys = [p[1] for p in posiciones]
        centro_x, centro_y = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        extension_x = max(max(xs) - min(xs), 1)
        extension_y = max(max(ys) - min(ys), 1)
        fraccion_vista = self.FRACCION_VISTA_GRANDE if grande else 0.8
        if grande and any(arista.source() == arista.target() for arista in visual.edges()):
            fraccion_vista = self.FRACCION_VISTA_CON_BUCLES
        escala = min(ancho * fraccion_vista / extension_x,
                     alto * fraccion_vista / extension_y)
        izquierda = centro_x - ancho / (2 * escala)
        arriba = centro_y - alto / (2 * escala)
        self._puntos = [
            QPointF((p[0] - izquierda) * escala, (p[1] - arriba) * escala)
            for p in posiciones
        ]
        rellenos = visual.new_vertex_property("string")
        colores_texto = visual.new_vertex_property("string")
        colores_arista = visual.new_edge_property("string")
        grosores = visual.new_edge_property("double")
        color_normal = self.COLOR_ARISTA_DENSA if denso else self.COLOR_ARISTA
        for vertice in visual.vertices():
            activo = int(vertice) in self._nodos_ruta
            rellenos[vertice] = self.COLOR_SELECCION if activo else self.FONDO_NODO
            colores_texto[vertice] = "#FFFFFF" if activo else self.COLOR_NODO
        for arista in visual.edges():
            par = (int(arista.source()), int(arista.target()))
            if not self._dirigido:
                par = tuple(sorted(par))
            activo = par in self._aristas_ruta
            colores_arista[arista] = self.COLOR_SELECCION if activo else color_normal
            grosores[arista] = 2.5 if activo else (1.0 if denso else self.GROSOR_ARISTA)
        salida = BytesIO()
        graph_draw(
            visual,
            pos=self._posiciones,
            output=salida,
            fmt="svg",
            output_size=(ancho, alto),
            fit_view=(izquierda, arriba, ancho / escala, alto / escala),
            vertex_text=self._nombres,
            vertex_fill_color=rellenos,
            vertex_color=self.COLOR_NODO,
            vertex_text_color=colores_texto,
            vertex_size=tamano_nodo,
            vertex_font_size=tamano_texto,
            vertex_font_family="DejaVu Sans",
            edge_color=colores_arista,
            edge_pen_width=grosores,
            edge_text=(self._pesos if visual.num_edges() <= self.LIMITE_ETIQUETAS_PESO
                       else None),
            edge_font_size=self.TAMANO_PESO,
            edge_font_family="DejaVu Sans",
            bg_color="#FFFFFF",
        )
        escena = self.scene()
        renderer_anterior = self._renderer
        escena.clear()
        if renderer_anterior is not None:
            renderer_anterior.deleteLater()
        self._renderer = QSvgRenderer(QByteArray(salida.getvalue()), self)
        dibujo = QGraphicsSvgItem()
        dibujo.setSharedRenderer(self._renderer)
        escena.addItem(dibujo)
        escena.setSceneRect(QRectF(0, 0, ancho, alto))
        transparente = QBrush(QColor(0, 0, 0, 1))
        for indice, punto in enumerate(self._puntos):
            radio = tamano_nodo / 2 + 3
            zona = escena.addEllipse(
                punto.x() - radio, punto.y() - radio, radio * 2, radio * 2,
                QPen(Qt.PenStyle.NoPen), transparente,
            )
            zona.setZValue(2)
            zona.setData(0, indice)
            zona.setToolTip(f"Nodo {self._identificadores[indice]}")
        if self._pesos is not None and (
            self._mapa_pesos is None
            or self._mapa_pesos.width() != ancho
            or self._mapa_pesos.height() != alto
        ):
            self._crear_mapa_pesos(ancho, alto, izquierda, arriba, escala, tamano_nodo)

    def _crear_mapa_pesos(self, ancho, alto, izquierda, arriba, escala, tamano_nodo) -> None:
        colores = self._visual.new_edge_property("string")
        self._peso_por_color.clear()
        for indice, arista in enumerate(self._visual.edges(), start=1):
            colores[arista] = f"#{indice:06x}"
            self._peso_por_color[indice] = self._pesos[arista]
        salida = BytesIO()
        graph_draw(
            self._visual,
            pos=self._posiciones,
            output=salida,
            fmt="png",
            output_size=(ancho, alto),
            fit_view=(izquierda, arriba, ancho / escala, alto / escala),
            vertex_shape="none",
            vertex_size=tamano_nodo,
            edge_color=colores,
            edge_pen_width=10,
            bg_color="#000000",
            antialias=cairo.Antialias.NONE,
        )
        self._mapa_pesos = QImage.fromData(salida.getvalue(), "PNG")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.position().toPoint())
            indice = item.data(0) if item is not None else None
            if (self._seleccion_habilitada and isinstance(indice, int)
                    and 0 <= indice < len(self._identificadores)):
                self.nodo_pulsado.emit(self._identificadores[indice])
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        super().mouseMoveEvent(event)
        if self._mapa_pesos is None:
            return
        item = self.itemAt(event.position().toPoint())
        if item is not None and isinstance(item.data(0), int):
            QToolTip.hideText()
            return
        punto = self.mapToScene(event.position().toPoint())
        x, y = int(punto.x()), int(punto.y())
        if 0 <= x < self._mapa_pesos.width() and 0 <= y < self._mapa_pesos.height():
            color = self._mapa_pesos.pixelColor(x, y)
            indice = (color.red() << 16) | (color.green() << 8) | color.blue()
            peso = self._peso_por_color.get(indice)
            if peso is not None:
                QToolTip.showText(event.globalPosition().toPoint(), f"Peso: {peso}", self)
                return
        QToolTip.hideText()

    def ajustar_vista(self) -> None:
        self.encuadrar()

    def encuadrar(self) -> None:
        if self.scene().items():
            self.resetTransform()
            self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
            self._escala = 1.0

    def wheelEvent(self, event) -> None:
        factor = 1.18 if event.angleDelta().y() > 0 else 1 / 1.18
        nueva_escala = self._escala * factor
        if 0.3 <= nueva_escala <= 8:
            self.scale(factor, factor)
            self._escala = nueva_escala


# Interfaz y ejecución
ESTILOS = """
QMainWindow, QWidget#raiz, QTabWidget::pane { background: #F3F6F8; }
QWidget { color: #193247; font-family: 'DejaVu Sans', 'Arial', sans-serif; font-size: 13px; }
QLabel#marca { color: #0E4D58; font-size: 24px; font-weight: 700; }
QLabel#subtitulo { color: #677C8B; font-size: 12px; }
QLabel#titulo { color: #153247; font-size: 22px; font-weight: 700; }
QLabel#seccion { color: #153247; font-size: 16px; font-weight: 700; }
QLabel#ayuda, QLabel#resumen { color: #607688; font-size: 12px; }
QLabel#error { color: #AF4339; font-weight: 600; }
QWidget#tarjeta { background: #FFFFFF; border: 1px solid #DDE6EB; border-radius: 15px; }
QTabWidget::pane { border: none; top: 0; }
QTabBar::tab { background: transparent; color: #667C8C; padding: 12px 25px;
               margin-right: 7px; border-bottom: 3px solid transparent; font-weight: 600; }
QTabBar::tab:selected { color: #0F6D72; border-bottom: 3px solid #0F8B8D; }
QTabBar::tab:disabled { color: #AAB8C1; }
QTabBar::tab:hover:!disabled { color: #0F6D72; }
QComboBox, QSpinBox { background: #F9FBFC; border: 1px solid #CAD9E1; border-radius: 8px;
                     padding: 8px 11px; min-height: 25px; }
QComboBox:focus, QSpinBox:focus { border: 1px solid #0F8B8D; }
QComboBox::drop-down { border: none; width: 24px; }
QPushButton { background: #EDF3F5; color: #174A63; border: 1px solid #D2E0E6;
              border-radius: 9px; padding: 10px 18px; font-weight: 700; min-height: 24px; }
QPushButton:hover { background: #DFEAED; }
QPushButton:pressed { background: #C9DCE0; }
QPushButton#primario { background: #0F6D72; color: white; border: 1px solid #0F6D72; }
QPushButton#primario:hover { background: #0B5559; }
QPushButton#acento { background: #D78157; color: white; border: 1px solid #D78157; }
QPushButton#acento:hover { background: #BD6942; }
QTableWidget { background: white; alternate-background-color: #F6F9FA;
               gridline-color: #E3EAEE; border: none; selection-background-color: #C8E8E8;
               selection-color: #153247; }
QHeaderView::section { background: #E9F0F3; color: #365568; border: none;
                       border-right: 1px solid #DCE7EB; border-bottom: 1px solid #DCE7EB;
                       padding: 7px; font-weight: 700; }
QScrollBar:vertical, QScrollBar:horizontal { background: #F1F5F7; border: none; width: 11px; height: 11px; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal { background: #B9CAD2; border-radius: 5px; min-height: 24px; min-width: 24px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
"""


def etiqueta(texto: str, estilo: str) -> QLabel:
    widget = QLabel(texto)
    widget.setObjectName(estilo)
    widget.setWordWrap(True)
    return widget


def tarjeta() -> tuple[QWidget, QVBoxLayout]:
    widget = QWidget()
    widget.setObjectName("tarjeta")
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(26, 24, 26, 24)
    layout.setSpacing(17)
    return widget, layout


class VentanaPrincipal(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._origen: str | None = None
        self._destino: str | None = None
        self._resultados: dict[str, ResultadoRuta] = {}
        self.setWindowTitle("Visualizador de Grafos")
        self.resize(1280, 820)
        self.setStyleSheet(ESTILOS)
        raiz = QWidget()
        raiz.setObjectName("raiz")
        estructura = QVBoxLayout(raiz)
        estructura.setContentsMargins(32, 24, 32, 24)
        estructura.setSpacing(19)
        estructura.addWidget(etiqueta("GRAFOS  /  OPTIMIZACIÓN", "marca"))
        estructura.addWidget(etiqueta("Construye, inspecciona y explora grafos desde su matriz de adyacencia.", "subtitulo"))
        self.pestanas = QTabWidget()
        self.configuracion = QWidget()
        self.matriz = QWidget()
        self.grafo = QWidget()
        self.pestanas.addTab(self.configuracion, "01  Configuración")
        self.pestanas.addTab(self.matriz, "02  Matriz")
        self.pestanas.addTab(self.grafo, "03  Grafo")
        self.pestanas.setTabEnabled(1, False)
        self.pestanas.setTabEnabled(2, False)
        estructura.addWidget(self.pestanas, 1)
        self.setCentralWidget(raiz)
        self._crear_configuracion()
        self._crear_matriz()
        self._crear_grafo()

    def _crear_configuracion(self) -> None:
        pagina = QVBoxLayout(self.configuracion)
        pagina.setContentsMargins(0, 24, 0, 0)
        pagina.setSpacing(21)
        pagina.addWidget(etiqueta("Configura tu grafo", "titulo"))
        pagina.addWidget(etiqueta("Elige sus propiedades y después constrúyelo manualmente o genera una matriz aleatoria.", "ayuda"))
        columnas = QHBoxLayout()
        columnas.setSpacing(22)
        pagina.addLayout(columnas, 1)
        opciones, izquierda = tarjeta()
        columnas.addWidget(opciones, 1)
        izquierda.addWidget(etiqueta("Propiedades", "seccion"))
        izquierda.addWidget(etiqueta("Definen los nodos y cómo se interpretan las relaciones.", "ayuda"))
        formulario = QFormLayout()
        formulario.setSpacing(15)
        formulario.setLabelAlignment(formulario.labelAlignment())
        self.cantidad_nodos = QSpinBox()
        self.cantidad_nodos.setRange(1, 50)
        self.cantidad_nodos.setValue(6)
        self.tipo_identificacion = QComboBox()
        self.tipo_identificacion.addItems(["Números", "Letras"])
        self.tipo_grafo = QComboBox()
        self.tipo_grafo.addItems(["No dirigido", "Dirigido"])
        self.ponderacion = QComboBox()
        self.ponderacion.addItems(["Sin pesos", "Con pesos"])
        self.ponderacion.currentIndexChanged.connect(self._actualizar_controles_peso)
        formulario.addRow("Número de nodos", self.cantidad_nodos)
        formulario.addRow("Identificación", self.tipo_identificacion)
        formulario.addRow("Tipo de grafo", self.tipo_grafo)
        formulario.addRow("Pesos", self.ponderacion)
        izquierda.addLayout(formulario)
        izquierda.addStretch()
        self.construir_btn = QPushButton("Construir manualmente")
        self.construir_btn.setObjectName("primario")
        self.construir_btn.clicked.connect(self._construir_manual)
        izquierda.addWidget(self.construir_btn)
        aleatorio, derecha = tarjeta()
        columnas.addWidget(aleatorio, 1)
        derecha.addWidget(etiqueta("Generación aleatoria", "seccion"))
        derecha.addWidget(etiqueta("Define una proporción aproximada de conexiones. La diagonal queda libre.", "ayuda"))
        formulario_aleatorio = QFormLayout()
        formulario_aleatorio.setSpacing(15)
        self.porcentaje = QSpinBox()
        self.porcentaje.setRange(0, 100)
        self.porcentaje.setValue(35)
        self.porcentaje.setSuffix(" %")
        self.peso_minimo = QSpinBox()
        self.peso_minimo.setRange(1, 1_000_000)
        self.peso_minimo.setValue(1)
        self.peso_maximo = QSpinBox()
        self.peso_maximo.setRange(1, 1_000_000)
        self.peso_maximo.setValue(10)
        formulario_aleatorio.addRow("Conexión", self.porcentaje)
        formulario_aleatorio.addRow("Peso mínimo", self.peso_minimo)
        formulario_aleatorio.addRow("Peso máximo", self.peso_maximo)
        self.etiqueta_minimo = formulario_aleatorio.labelForField(self.peso_minimo)
        self.etiqueta_maximo = formulario_aleatorio.labelForField(self.peso_maximo)
        derecha.addLayout(formulario_aleatorio)
        derecha.addStretch()
        self.generar_btn = QPushButton("Generar aleatoriamente")
        self.generar_btn.setObjectName("acento")
        self.generar_btn.clicked.connect(self._generar_aleatorio)
        derecha.addWidget(self.generar_btn)
        self._actualizar_controles_peso()
        self.mensaje_configuracion = etiqueta("", "error")
        pagina.addWidget(self.mensaje_configuracion)

    def _crear_matriz(self) -> None:
        pagina = QVBoxLayout(self.matriz)
        pagina.setContentsMargins(0, 24, 0, 0)
        pagina.setSpacing(18)
        pagina.addWidget(etiqueta("Matriz de adyacencia", "titulo"))
        self.resumen_matriz = etiqueta("", "resumen")
        pagina.addWidget(self.resumen_matriz)
        contenedor, layout = tarjeta()
        pagina.addWidget(contenedor, 1)
        self.vista_matriz = MatrizAdyacencia()
        self.vista_matriz.on_error = self.mostrar_error
        self.vista_matriz.on_graficar = self.graficar
        layout.addWidget(self.vista_matriz, 1)
        self.mensaje_matriz = etiqueta("", "error")
        pagina.addWidget(self.mensaje_matriz)

    def _crear_grafo(self) -> None:
        pagina = QVBoxLayout(self.grafo)
        pagina.setContentsMargins(0, 16, 0, 0)
        pagina.setSpacing(10)
        encabezado = QHBoxLayout()
        titulos = QVBoxLayout()
        titulos.addWidget(etiqueta("Vista del grafo", "titulo"))
        self.resumen_grafo = etiqueta("Rueda para ampliar · Arrastra para desplazarte", "resumen")
        titulos.addWidget(self.resumen_grafo)
        encabezado.addLayout(titulos, 1)
        self.algoritmo = QComboBox()
        self.algoritmo.addItems(["Dijkstra", "Bellman-Ford"])
        self.algoritmo.setMinimumWidth(170)
        self.algoritmo.currentIndexChanged.connect(self._cambiar_algoritmo)
        encabezado.addWidget(self.algoritmo)
        self.ajustar_btn = QPushButton("Ajustar vista")
        encabezado.addWidget(self.ajustar_btn)
        pagina.addLayout(encabezado)
        self.alerta_ruta = etiqueta("", "error")
        pagina.addWidget(self.alerta_ruta)

        division = QSplitter(Qt.Orientation.Vertical)
        pagina.addWidget(division, 1)
        contenedor, layout = tarjeta()
        layout.setContentsMargins(8, 8, 8, 8)
        division.addWidget(contenedor)
        self.visualizador = VisualizadorGrafo()
        self.visualizador.nodo_pulsado.connect(self._pulsar_nodo)
        self.ajustar_btn.clicked.connect(self.visualizador.ajustar_vista)
        layout.addWidget(self.visualizador)

        resultados, layout_resultados = tarjeta()
        layout_resultados.setContentsMargins(16, 12, 16, 12)
        layout_resultados.setSpacing(6)
        division.addWidget(resultados)
        self.tablas: dict[str, QTableWidget] = {}
        self.resumenes: dict[str, QLabel] = {}
        for nombre in ("Dijkstra", "Bellman-Ford"):
            layout_resultados.addWidget(etiqueta(f"Solución por algoritmo de {nombre}", "seccion"))
            resumen = etiqueta("Elige origen y destino para ver los pasos.", "resumen")
            layout_resultados.addWidget(resumen)
            tabla = QTableWidget()
            tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            tabla.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
            tabla.setAlternatingRowColors(True)
            tabla.horizontalHeader().setDefaultSectionSize(105)
            tabla.setMinimumHeight(120)
            layout_resultados.addWidget(tabla, 1)
            self.tablas[nombre] = tabla
            self.resumenes[nombre] = resumen
        self.comparacion = etiqueta("", "resumen")
        layout_resultados.addWidget(self.comparacion)
        division.setChildrenCollapsible(False)
        division.setStretchFactor(0, 3)
        division.setStretchFactor(1, 2)
        division.setSizes([420, 320])

    def _actualizar_controles_peso(self) -> None:
        visible = self.ponderacion.currentIndex() == 1
        for widget in (self.peso_minimo, self.peso_maximo,
                       self.etiqueta_minimo, self.etiqueta_maximo):
            widget.setVisible(visible)

    def mostrar_error(self, texto: str) -> None:
        self.mensaje_matriz.setText(texto)

    def _nuevo_grafo(self, grafo: Grafo, editable: bool) -> None:
        self._limpiar_resultados()
        self.vista_matriz.preparar(grafo, editable=editable)
        tipo = "dirigido" if grafo.dirigido else "no dirigido"
        pesos = "con pesos" if grafo.ponderado else "sin pesos"
        origen = "editable" if editable else "generada aleatoriamente"
        self.resumen_matriz.setText(
            f"{len(grafo.nodos)} nodos · {tipo} · {pesos} · matriz {origen}"
        )
        self.mensaje_configuracion.clear()
        self.mensaje_matriz.clear()
        self.pestanas.setTabEnabled(1, True)
        self.pestanas.setCurrentIndex(1)
        self.pestanas.setTabEnabled(2, False)

    def _construir_manual(self) -> None:
        nodos = identificadores(self.cantidad_nodos.value(), self.tipo_identificacion.currentText())
        grafo = Grafo(nodos, self.tipo_grafo.currentIndex() == 1,
                      self.ponderacion.currentIndex() == 1)
        self._nuevo_grafo(grafo, editable=True)

    def _generar_aleatorio(self) -> None:
        ponderado = self.ponderacion.currentIndex() == 1
        minimo, maximo = self.peso_minimo.value(), self.peso_maximo.value()
        if ponderado and minimo > maximo:
            self.mensaje_configuracion.setText("El peso mínimo debe ser menor o igual al máximo.")
            return
        nodos = identificadores(self.cantidad_nodos.value(), self.tipo_identificacion.currentText())
        grafo = Grafo(nodos, self.tipo_grafo.currentIndex() == 1, ponderado)
        if grafo.dirigido:
            posibles = ((a, b) for a in nodos for b in nodos if a != b)
        else:
            posibles = ((nodos[i], nodos[j]) for i in range(len(nodos))
                        for j in range(i + 1, len(nodos)))
        for origen, destino in posibles:
            if random.random() * 100 < self.porcentaje.value():
                peso = random.randint(minimo, maximo) if ponderado else None
                grafo.agregar_arista(origen, destino, peso)
        self._nuevo_grafo(grafo, editable=False)

    def graficar(self) -> None:
        grafo = self.vista_matriz.grafo
        if grafo is None:
            self.mostrar_error("Construya o genere un grafo antes de graficar.")
            return
        cantidad_aristas = sum(1 for _ in grafo.aristas())
        texto = f"{len(grafo.nodos)} nodos · {cantidad_aristas} aristas · rueda para ampliar · arrastra para desplazarte"
        if grafo.ponderado and cantidad_aristas > 70:
            texto += " · pasa el cursor por una arista para ver su peso"
        if grafo.ponderado:
            texto += " · haz clic en origen y destino"
        self.resumen_grafo.setText(texto)
        self._limpiar_resultados()
        self.algoritmo.blockSignals(True)
        self.algoritmo.setCurrentIndex(1 if grafo.tiene_pesos_negativos() else 0)
        self.algoritmo.blockSignals(False)
        self.algoritmo.setEnabled(grafo.ponderado)
        self.pestanas.setTabEnabled(2, True)
        self.pestanas.setCurrentIndex(2)
        self.visualizador.mostrar(grafo)
        QTimer.singleShot(0, self.visualizador.encuadrar)
        self.mensaje_matriz.clear()

    def _limpiar_resultados(self) -> None:
        self._origen = None
        self._destino = None
        self._resultados.clear()
        for nombre, tabla in self.tablas.items():
            tabla.clear()
            tabla.setRowCount(0)
            tabla.setColumnCount(0)
            self.resumenes[nombre].setText("Elige origen y destino para ver los pasos.")
        self.comparacion.clear()
        self.alerta_ruta.clear()

    def _pulsar_nodo(self, nodo: str) -> None:
        grafo = self.vista_matriz.grafo
        if grafo is None or not grafo.ponderado:
            return
        if self._origen is None or self._destino is not None:
            self._limpiar_resultados()
            self._origen = nodo
            self.visualizador.resaltar_ruta([])
            self.resumen_grafo.setText(f"Origen: {nodo} · elige el destino")
            return
        self._destino = nodo
        self._mostrar_algoritmo()

    def _cambiar_algoritmo(self) -> None:
        grafo = self.vista_matriz.grafo
        if grafo is None or not grafo.ponderado:
            return
        if self.algoritmo.currentText() == "Dijkstra" and grafo.tiene_pesos_negativos():
            self.algoritmo.blockSignals(True)
            self.algoritmo.setCurrentText("Bellman-Ford")
            self.algoritmo.blockSignals(False)
            self.alerta_ruta.setText("Dijkstra no admite pesos negativos. Usa Bellman-Ford.")
            return
        self.alerta_ruta.clear()
        if self._origen is not None and self._destino is not None:
            self._mostrar_algoritmo()

    def _mostrar_algoritmo(self) -> None:
        nombre = self.algoritmo.currentText()
        resultado = self._resultados.get(nombre)
        if resultado is None:
            grafo = self.vista_matriz.grafo
            resultado = grafo.calcular_ruta(self._origen, self._destino, nombre)
            self._resultados[nombre] = resultado
            self._llenar_tabla(nombre, resultado)
        if resultado.estado == "ruta":
            camino = " → ".join(str(nodo) for nodo in resultado.ruta)
            resumen = f"Ruta: {camino} · costo total: {resultado.distancia:g}"
        elif resultado.estado == "sin_ruta":
            resumen = f"Sin ruta entre {self._origen} y {self._destino}"
        else:
            resumen = "Un ciclo negativo impide una distancia mínima finita."
        if resultado.ciclo_negativo and resultado.estado != "ciclo_negativo":
            resumen += " · Hay un ciclo negativo alcanzable desde el origen."
        self.resumenes[nombre].setText(resumen)
        self.resumen_grafo.setText(resumen)
        self.visualizador.resaltar_ruta(resultado.ruta)
        otro = "Bellman-Ford" if nombre == "Dijkstra" else "Dijkstra"
        comparado = self._resultados.get(otro)
        if comparado is not None and resultado.estado == comparado.estado == "ruta":
            self.comparacion.setText(
                f"Comparación: ambos algoritmos obtienen costo {resultado.distancia:g}."
            )

    def _llenar_tabla(self, nombre: str, resultado: ResultadoRuta) -> None:
        tabla = self.tablas[nombre]
        nodos = self.vista_matriz.grafo.nodos
        tabla.setRowCount(len(nodos))
        tabla.setColumnCount(len(resultado.pasos) + 1)
        tabla.verticalHeader().hide()
        tabla.setHorizontalHeaderLabels(
            ["Vértice", "Inicio"]
            + [f"Paso {indice}" for indice in range(1, len(resultado.pasos))]
        )
        tabla.setColumnWidth(0, 75)
        for fila, nodo in enumerate(nodos):
            tabla.setItem(fila, 0, QTableWidgetItem(str(nodo)))
        for columna, paso in enumerate(resultado.pasos, start=1):
            for fila, nodo in enumerate(nodos):
                distancia = paso.distancias[nodo]
                if distancia == float("inf"):
                    texto = "—"
                else:
                    previo = paso.previos[nodo]
                    texto = f"({distancia:g}, {previo if previo is not None else '—'})"
                celda = QTableWidgetItem(texto)
                if nodo in paso.destacados:
                    celda.setBackground(QColor("#C8E8E8"))
                tabla.setItem(fila, columna, celda)


def main() -> int:
    app = QApplication(sys.argv)
    ventana = VentanaPrincipal()
    ventana.showMaximized()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
