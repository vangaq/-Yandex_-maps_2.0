#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Приложение Яндекс.Карты на PyQt6
"""

import sys
import math
import requests
from io import BytesIO
from typing import Optional, Tuple, List

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QComboBox, QCheckBox,
    QGroupBox, QMessageBox, QSizePolicy
)
from PyQt6.QtGui import QPixmap, QImage, QKeyEvent, QMouseEvent, QCursor
from PyQt6.QtCore import Qt, QTimer, pyqtSignal

# API ключи
API_KEY_STATIC = 'f3a0fe3a-b07e-4840-a1da-06f18b2ddf13'
API_KEY_GEOCODER = '8013b162-6b42-4997-9691-77b7074026e0'  # Тот же ключ для геокодера
API_KEY_SEARCH = 'f3a0fe3a-b07e-4840-a1da-06f18b2ddf13'  # Для поиска организаций

# URL API
STATIC_MAPS_URL = 'https://static-maps.yandex.ru/v1'
GEOCODER_URL = 'https://geocode-maps.yandex.ru/1.x/'
SEARCH_URL = 'https://search-maps.yandex.ru/v1/'

# Константы карты
MIN_ZOOM = 1
MAX_ZOOM = 17
MIN_LON = -180
MAX_LON = 180
MIN_LAT = -85
MAX_LAT = 85

# Размеры карты
MAP_WIDTH = 600
MAP_HEIGHT = 450

# Сдвиг при перемещении (в долях от размера экрана)
MOVE_FACTOR = 0.5


class MapWidget(QLabel):
    """Виджет для отображения карты с поддержкой кликов"""
    
    leftClicked = pyqtSignal(float, float)  # lon, lat
    rightClicked = pyqtSignal(float, float)  # lon, lat
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(MAP_WIDTH, MAP_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background-color: #f0f0f0; border: 1px solid #ccc;")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
        
    def mousePressEvent(self, event: QMouseEvent):
        if self.pixmap() is None:
            return
            
        # Получаем координаты клика относительно виджета
        click_x = event.position().x()
        click_y = event.position().y()
        
        # Получаем размеры отображаемого изображения
        pixmap = self.pixmap()
        img_width = pixmap.width()
        img_height = pixmap.height()
        
        # Получаем размеры виджета
        widget_width = self.width()
        widget_height = self.height()
        
        # Вычисляем смещение изображения (если оно центрировано)
        offset_x = (widget_width - img_width) / 2
        offset_y = (widget_height - img_height) / 2
        
        # Проверяем, что клик внутри изображения
        if not (offset_x <= click_x <= offset_x + img_width and 
                offset_y <= click_y <= offset_y + img_height):
            return
            
        # Нормализуем координаты относительно изображения (-1 до 1)
        norm_x = (click_x - offset_x - img_width / 2) / (img_width / 2)
        norm_y = -(click_y - offset_y - img_height / 2) / (img_height / 2)
        
        # Эмитируем сигнал с нормализованными координатами
        if event.button() == Qt.MouseButton.LeftButton:
            self.leftClicked.emit(norm_x, norm_y)
        elif event.button() == Qt.MouseButton.RightButton:
            self.rightClicked.emit(norm_x, norm_y)


class YandexMapsApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Яндекс.Карты - PyQt6")
        self.setMinimumSize(900, 700)
        
        # Текущие параметры карты
        self.zoom = 10
        self.lon = 37.6176  # Москва по умолчанию
        self.lat = 55.7558
        
        # Тема и тип карты
        self.theme = "light"  # light / dark
        self.map_type = "map"  # map / sat / sat,skl / map,trf / map,adm
        
        # Поисковые результаты
        self.marker_lon: Optional[float] = None
        self.marker_lat: Optional[float] = None
        self.current_address: str = ""
        self.current_postal_code: str = ""
        
        # Флаг включения почтового индекса
        self.include_postal_code = False
        
        # Инициализация UI
        self.init_ui()
        
        # Загрузка начальной карты
        self.load_map()
        
    def init_ui(self):
        """Инициализация интерфейса"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Главный layout
        main_layout = QHBoxLayout(central_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # Левая панель - карта
        left_panel = QVBoxLayout()
        
        # Виджет карты
        self.map_widget = MapWidget()
        self.map_widget.leftClicked.connect(self.on_map_left_click)
        self.map_widget.rightClicked.connect(self.on_map_right_click)
        left_panel.addWidget(self.map_widget)
        
        # Подпись под картой
        hint_label = QLabel(
            "PgUp/PgDown - масштаб | Стрелки - перемещение | "
            "ЛКМ - поиск координат | ПКМ - поиск организации"
        )
        hint_label.setStyleSheet("color: #666; font-size: 11px;")
        hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_panel.addWidget(hint_label)
        
        main_layout.addLayout(left_panel, stretch=2)
        
        # Правая панель - управление
        right_panel = QVBoxLayout()
        right_panel.setSpacing(10)
        
        # Группа поиска
        search_group = QGroupBox("Поиск объекта")
        search_layout = QVBoxLayout(search_group)
        
        # Поле ввода запроса
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Введите адрес или объект...")
        self.search_input.returnPressed.connect(self.search_object)
        search_layout.addWidget(self.search_input)
        
        # Кнопка поиска
        search_btn = QPushButton("Искать")
        search_btn.clicked.connect(self.search_object)
        search_layout.addWidget(search_btn)
        
        # Кнопка сброса
        reset_btn = QPushButton("Сбросить результат")
        reset_btn.clicked.connect(self.reset_search)
        search_layout.addWidget(reset_btn)
        
        right_panel.addWidget(search_group)
        
        # Группа адреса
        address_group = QGroupBox("Адрес объекта")
        address_layout = QVBoxLayout(address_group)
        
        self.address_label = QLabel("Адрес не найден")
        self.address_label.setWordWrap(True)
        self.address_label.setStyleSheet("padding: 5px; background: #f9f9f9; border-radius: 3px;")
        address_layout.addWidget(self.address_label)
        
        # Чекбокс почтового индекса
        self.postal_checkbox = QCheckBox("Добавлять почтовый индекс")
        self.postal_checkbox.stateChanged.connect(self.on_postal_toggle)
        address_layout.addWidget(self.postal_checkbox)
        
        right_panel.addWidget(address_group)
        
        # Группа настроек карты
        settings_group = QGroupBox("Настройки карты")
        settings_layout = QVBoxLayout(settings_group)
        
        # Тема карты
        theme_layout = QHBoxLayout()
        theme_layout.addWidget(QLabel("Тема:"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Светлая", "Тёмная"])
        self.theme_combo.currentIndexChanged.connect(self.on_theme_changed)
        theme_layout.addWidget(self.theme_combo)
        settings_layout.addLayout(theme_layout)
        
        # Тип карты
        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("Вид:"))
        self.type_combo = QComboBox()
        self.type_combo.addItems([
            "Базовая карта",
            "Спутник",
            "Спутник + метки",
            "Автомобильная навигация",
            "Общественный транспорт",
            "Административная"
        ])
        self.type_combo.currentIndexChanged.connect(self.on_type_changed)
        type_layout.addWidget(self.type_combo)
        settings_layout.addLayout(type_layout)
        
        # Отображение текущих координат
        coords_layout = QHBoxLayout()
        coords_layout.addWidget(QLabel("Координаты:"))
        self.coords_label = QLabel(f"{self.lon:.4f}, {self.lat:.4f}")
        self.coords_label.setStyleSheet("font-family: monospace;")
        coords_layout.addWidget(self.coords_label)
        settings_layout.addLayout(coords_layout)
        
        # Отображение масштаба
        zoom_layout = QHBoxLayout()
        zoom_layout.addWidget(QLabel("Масштаб:"))
        self.zoom_label = QLabel(str(self.zoom))
        zoom_layout.addWidget(self.zoom_label)
        settings_layout.addLayout(zoom_layout)
        
        right_panel.addWidget(settings_group)
        
        # Растягивающийся spacer
        right_panel.addStretch()
        
        main_layout.addLayout(right_panel, stretch=1)
        
        # Установка фокуса на карту для обработки клавиш
        self.map_widget.setFocus()
        
    def keyPressEvent(self, event: QKeyEvent):
        """Обработка нажатий клавиш"""
        key = event.key()
        
        if key == Qt.Key.Key_PageUp:
            self.change_zoom(1)
        elif key == Qt.Key.Key_PageDown:
            self.change_zoom(-1)
        elif key == Qt.Key.Key_Up:
            self.move_map(0, 1)
        elif key == Qt.Key.Key_Down:
            self.move_map(0, -1)
        elif key == Qt.Key.Key_Left:
            self.move_map(-1, 0)
        elif key == Qt.Key.Key_Right:
            self.move_map(1, 0)
        else:
            super().keyPressEvent(event)
            
    def change_zoom(self, delta: int):
        """Изменение масштаба"""
        new_zoom = self.zoom + delta
        if MIN_ZOOM <= new_zoom <= MAX_ZOOM:
            self.zoom = new_zoom
            self.zoom_label.setText(str(self.zoom))
            self.load_map()
            
    def move_map(self, dx: int, dy: int):
        """Перемещение карты"""
        # Вычисляем размер видимой области в градусах
        # Приближенная формула: ширина в градусах = 360 / 2^zoom
        span_lon = 360 / (2 ** self.zoom)
        span_lat = 180 / (2 ** self.zoom)
        
        # Применяем сдвиг
        new_lon = self.lon + dx * span_lon * MOVE_FACTOR
        new_lat = self.lat + dy * span_lat * MOVE_FACTOR
        
        # Проверяем границы
        if MIN_LON <= new_lon <= MAX_LON:
            self.lon = new_lon
        if MIN_LAT <= new_lat <= MAX_LAT:
            self.lat = new_lat
            
        self.coords_label.setText(f"{self.lon:.4f}, {self.lat:.4f}")
        self.load_map()
        
    def on_theme_changed(self, index: int):
        """Изменение темы карты"""
        self.theme = "dark" if index == 1 else "light"
        self.load_map()
        
    def on_type_changed(self, index: int):
        """Изменение типа карты"""
        map_types = {
            0: "map",           # Базовая
            1: "sat",           # Спутник
            2: "sat,skl",       # Спутник + метки
            3: "map,trf",       # Автонавигация
            4: "map,trf,pt",    # Общественный транспорт
            5: "map,adm"        # Административная
        }
        self.map_type = map_types.get(index, "map")
        self.load_map()
        
    def on_postal_toggle(self, state: int):
        """Переключение почтового индекса"""
        self.include_postal_code = state == Qt.CheckState.Checked.value
        self.update_address_display()
        
    def update_address_display(self):
        """Обновление отображения адреса"""
        if not self.current_address:
            self.address_label.setText("Адрес не найден")
            return
            
        if self.include_postal_code and self.current_postal_code:
            self.address_label.setText(f"{self.current_address}, {self.current_postal_code}")
        else:
            self.address_label.setText(self.current_address)
            
    def get_map_url(self) -> str:
        """Формирование URL для загрузки карты"""
        params = {
            'apikey': API_KEY_STATIC,
            'll': f"{self.lon},{self.lat}",
            'z': self.zoom,
            'l': self.map_type,
            'size': f"{MAP_WIDTH},{MAP_HEIGHT}",
            'theme': self.theme
        }
        
        # Добавляем метку если есть
        if self.marker_lon is not None and self.marker_lat is not None:
            params['pt'] = f"{self.marker_lon},{self.marker_lat},pm2rdl"
            
        # Формируем URL
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{STATIC_MAPS_URL}?{query}"
        
    def load_map(self):
        """Загрузка карты из API"""
        try:
            url = self.get_map_url()
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                image = QImage.fromData(response.content)
                pixmap = QPixmap.fromImage(image)
                self.map_widget.setPixmap(pixmap)
            else:
                self.map_widget.setText(f"Ошибка загрузки карты: {response.status_code}")
                
        except Exception as e:
            self.map_widget.setText(f"Ошибка: {str(e)}")
            
    def search_object(self):
        """Поиск объекта по запросу"""
        query = self.search_input.text().strip()
        if not query:
            QMessageBox.warning(self, "Предупреждение", "Введите запрос для поиска")
            return
            
        try:
            params = {
                'apikey': API_KEY_GEOCODER,
                'geocode': query,
                'format': 'json',
                'results': 1
            }
            
            response = requests.get(GEOCODER_URL, params=params, timeout=10)
            data = response.json()
            
            if response.status_code == 200 and data.get('response'):
                feature_members = data['response']['GeoObjectCollection']['featureMember']
                
                if feature_members:
                    geo_object = feature_members[0]['GeoObject']
                    pos = geo_object['Point']['pos']
                    lon, lat = map(float, pos.split())
                    
                    # Обновляем координаты и масштаб
                    self.lon = lon
                    self.lat = lat
                    self.zoom = 15  # Увеличиваем масштаб для найденного объекта
                    
                    # Устанавливаем метку
                    self.marker_lon = lon
                    self.marker_lat = lat
                    
                    # Получаем адрес
                    self.current_address = geo_object.get('metaDataProperty', {}).get(
                        'GeocoderMetaData', {}).get('text', 'Адрес не найден')
                    
                    # Пытаемся получить почтовый индекс
                    try:
                        components = geo_object.get('metaDataProperty', {}).get(
                            'GeocoderMetaData', {}).get('Address', {}).get('Components', [])
                        self.current_postal_code = geo_object.get('metaDataProperty', {}).get(
                            'GeocoderMetaData', {}).get('Address', {}).get('postal_code', '')
                    except:
                        self.current_postal_code = ""
                    
                    # Обновляем UI
                    self.coords_label.setText(f"{self.lon:.4f}, {self.lat:.4f}")
                    self.zoom_label.setText(str(self.zoom))
                    self.update_address_display()
                    self.load_map()
                    
                else:
                    QMessageBox.information(self, "Результат", "Объект не найден")
                    
            else:
                QMessageBox.warning(self, "Ошибка", "Не удалось выполнить поиск")
                
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка при поиске: {str(e)}")
            
    def reset_search(self):
        """Сброс поискового результата"""
        self.marker_lon = None
        self.marker_lat = None
        self.current_address = ""
        self.current_postal_code = ""
        self.address_label.setText("Адрес не найден")
        self.search_input.clear()
        self.load_map()
        
    def on_map_left_click(self, norm_x: float, norm_y: float):
        """Обработка левого клика по карте - поиск координат"""
        # Вычисляем размер видимой области
        span_lon = 360 / (2 ** self.zoom)
        span_lat = 180 / (2 ** self.zoom)
        
        # Вычисляем новые координаты
        click_lon = self.lon + norm_x * span_lon / 2
        click_lat = self.lat + norm_y * span_lat / 2
        
        # Ограничиваем координаты
        click_lon = max(MIN_LON, min(MAX_LON, click_lon))
        click_lat = max(MIN_LAT, min(MAX_LAT, click_lat))
        
        # Сбрасываем предыдущий результат
        self.reset_search()
        
        # Устанавливаем новую метку
        self.marker_lon = click_lon
        self.marker_lat = click_lat
        
        # Выполняем обратное геокодирование
        self.reverse_geocode(click_lon, click_lat)
        
    def reverse_geocode(self, lon: float, lat: float):
        """Обратное геокодирование - получение адреса по координатам"""
        try:
            params = {
                'apikey': API_KEY_GEOCODER,
                'geocode': f"{lon},{lat}",
                'format': 'json',
                'results': 1,
                'kind': 'house'  # Ищем ближайшее здание
            }
            
            response = requests.get(GEOCODER_URL, params=params, timeout=10)
            data = response.json()
            
            if response.status_code == 200 and data.get('response'):
                feature_members = data['response']['GeoObjectCollection']['featureMember']
                
                if feature_members:
                    geo_object = feature_members[0]['GeoObject']
                    
                    # Получаем адрес
                    self.current_address = geo_object.get('metaDataProperty', {}).get(
                        'GeocoderMetaData', {}).get('text', 'Адрес не найден')
                    
                    # Пытаемся получить почтовый индекс
                    try:
                        self.current_postal_code = geo_object.get('metaDataProperty', {}).get(
                            'GeocoderMetaData', {}).get('Address', {}).get('postal_code', '')
                    except:
                        self.current_postal_code = ""
                    
                    self.update_address_display()
                    self.load_map()
                    
        except Exception as e:
            print(f"Ошибка обратного геокодирования: {e}")
            
    def on_map_right_click(self, norm_x: float, norm_y: float):
        """Обработка правого клика по карте - поиск организации"""
        # Вычисляем размер видимой области
        span_lon = 360 / (2 ** self.zoom)
        span_lat = 180 / (2 ** self.zoom)
        
        # Вычисляем новые координаты
        click_lon = self.lon + norm_x * span_lon / 2
        click_lat = self.lat + norm_y * span_lat / 2
        
        # Ограничиваем координаты
        click_lon = max(MIN_LON, min(MAX_LON, click_lon))
        click_lat = max(MIN_LAT, min(MAX_LAT, click_lat))
        
        # Сбрасываем предыдущий результат
        self.reset_search()
        
        # Устанавливаем метку
        self.marker_lon = click_lon
        self.marker_lat = click_lat
        
        # Ищем организацию
        self.search_organization(click_lon, click_lat)
        
    def search_organization(self, lon: float, lat: float):
        """Поиск организации по координатам"""
        try:
            params = {
                'apikey': API_KEY_SEARCH,
                'text': "организация",
                'll': f"{lon},{lat}",
                'spn': '0.001,0.001',  # Небольшой радиус поиска
                'type': 'biz',
                'results': 5,
                'lang': 'ru_RU'
            }
            
            response = requests.get(SEARCH_URL, params=params, timeout=10)
            data = response.json()
            
            if response.status_code == 200 and data.get('features'):
                # Ищем первую организацию в радиусе 50 метров
                for feature in data['features']:
                    org_lon, org_lat = feature['geometry']['coordinates']
                    
                    # Вычисляем расстояние
                    distance = self.haversine_distance(lat, lon, org_lat, org_lon)
                    
                    if distance <= 50:  # 50 метров
                        # Нашли подходящую организацию
                        properties = feature.get('properties', {})
                        company_meta = properties.get('CompanyMetaData', {})
                        
                        org_name = company_meta.get('name', 'Неизвестная организация')
                        org_address = company_meta.get('address', 'Адрес не указан')
                        
                        self.current_address = f"{org_name}\n{org_address}"
                        self.current_postal_code = ""
                        
                        # Обновляем координаты метки на координаты организации
                        self.marker_lon = org_lon
                        self.marker_lat = org_lat
                        
                        self.update_address_display()
                        self.load_map()
                        return
                
                # Если не нашли организацию в радиусе 50 метров
                self.current_address = "Организация не найдена (в радиусе 50м)"
                self.update_address_display()
                self.load_map()
                
            else:
                self.current_address = "Организации не найдены"
                self.update_address_display()
                self.load_map()
                
        except Exception as e:
            print(f"Ошибка поиска организации: {e}")
            
    def haversine_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Вычисление расстояния между двумя точками на сфере (в метрах)"""
        R = 6371000  # Радиус Земли в метрах
        
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)
        
        a = math.sin(delta_phi / 2) ** 2 + \
            math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        
        return R * c


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    # Установка шрифта
    font = app.font()
    font.setPointSize(10)
    app.setFont(font)
    
    window = YandexMapsApp()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
