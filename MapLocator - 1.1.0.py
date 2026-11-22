#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
地址定位与街景查看系统 - 增强版
功能：输入地址，显示地图位置和街景，支持国内外多种地图服务
地图支持：OpenStreetMap, CartoDB, Stamen Terrain, Stamen Toner, 卫星图等
街景支持：百度街景(国内), Google街景, Mapillary街景(国外免费)
"""

import sys
import os
import json
import sqlite3
import shutil
import hashlib
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
import re
from pypinyin import pinyin, lazy_pinyin, Style
import urllib.parse
import urllib.request
import logging
import math

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QTabWidget,
    QStatusBar, QProgressBar, QMessageBox, QFileDialog,
    QDialog, QTableWidget, QTableWidgetItem, QHeaderView,
    QSplitter, QGroupBox, QCheckBox, QSpinBox, QTextEdit,
    QDateTimeEdit, QDialogButtonBox, QRadioButton, QButtonGroup,
    QSystemTrayIcon, QMenu, QStyle, QFrame, QToolBar,
    QListWidget, QListWidgetItem, QStackedWidget, QGridLayout,
    QSlider, QScrollArea
)
from PySide6.QtCore import (
    Qt, QThread, Signal, QUrl, QSettings, QTimer,
    QDateTime, QMutex, QWaitCondition, QCoreApplication,
    QSize, QRect, QPoint
)
from PySide6.QtGui import QIcon, QAction, QPainter, QColor, QPixmap, QFont
from PySide6.QtWebEngineWidgets import QWebEngineView

# 调试模式配置
DEBUG_MODE = False  # 默认关闭调试模式

# 配置日志
if DEBUG_MODE:
    logging.basicConfig(level=logging.DEBUG,
                       format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
else:
    logging.basicConfig(level=logging.WARNING,
                       format='%(asctime)s - %(levelname)s - %(message)s')

logger = logging.getLogger(__name__)


class EnhancedMapTileManager:
    """增强的地图瓦片管理器"""
    
    # 地图样式定义
    MAP_STYLES = {
        'openstreetmap': {
            'name': 'OpenStreetMap',
            'url': 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
            'attribution': '© OpenStreetMap contributors',
            'max_zoom': 19,
            'subdomains': ['a', 'b', 'c']
        },
        'cartodb_positron': {
            'name': 'CartoDB Positron',
            'url': 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png',
            'attribution': '© CartoDB, © OpenStreetMap contributors',
            'max_zoom': 19,
            'subdomains': ['a', 'b', 'c', 'd']
        },
        'cartodb_dark': {
            'name': 'CartoDB Dark Matter',
            'url': 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',
            'attribution': '© CartoDB, © OpenStreetMap contributors',
            'max_zoom': 19,
            'subdomains': ['a', 'b', 'c', 'd']
        },
        'stamen_terrain': {
            'name': 'Stamen Terrain',
            'url': 'https://stamen-tiles-{s}.a.ssl.fastly.net/terrain-background/{z}/{x}/{y}.png',
            'attribution': 'Map tiles by Stamen Design, under CC BY 3.0. Data by OpenStreetMap, under ODbL.',
            'max_zoom': 16,
            'subdomains': ['a', 'b', 'c', 'd']
        },
        'stamen_toner': {
            'name': 'Stamen Toner',
            'url': 'https://stamen-tiles-{s}.a.ssl.fastly.net/toner/{z}/{x}/{y}.png',
            'attribution': 'Map tiles by Stamen Design, under CC BY 3.0. Data by OpenStreetMap, under ODbL.',
            'max_zoom': 20,
            'subdomains': ['a', 'b', 'c', 'd']
        },
        'stamen_watercolor': {
            'name': 'Stamen Watercolor',
            'url': 'https://stamen-tiles-{s}.a.ssl.fastly.net/watercolor/{z}/{x}/{y}.jpg',
            'attribution': 'Map tiles by Stamen Design, under CC BY 3.0. Data by OpenStreetMap, under ODbL.',
            'max_zoom': 16,
            'subdomains': ['a', 'b', 'c', 'd']
        },
        'esri_satellite': {
            'name': 'ESRI 卫星图',
            'url': 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
            'attribution': 'Esri, Maxar, Earthstar Geographics, and the GIS User Community',
            'max_zoom': 19,
            'subdomains': []
        },
        'esri_streets': {
            'name': 'ESRI 街道图',
            'url': 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}',
            'attribution': 'Esri, HERE, Garmin, USGS, NGA',
            'max_zoom': 19,
            'subdomains': []
        },
        'wikimedia': {
            'name': 'Wikimedia',
            'url': 'https://maps.wikimedia.org/osm-intl/{z}/{x}/{y}.png',
            'attribution': '© Wikimedia maps, © OpenStreetMap contributors',
            'max_zoom': 19,
            'subdomains': []
        }
    }
    
    @classmethod
    def get_style_names(cls):
        """获取所有样式名称"""
        return [(key, value['name']) for key, value in cls.MAP_STYLES.items()]
    
    @classmethod
    def get_style_config(cls, style_key: str) -> Dict:
        """获取样式配置"""
        return cls.MAP_STYLES.get(style_key, cls.MAP_STYLES['openstreetmap'])


class EnhancedStreetViewManager:
    """增强的街景管理器"""
    
    STREET_VIEW_PROVIDERS = {
        'baidu': {
            'name': '百度街景',
            'region': 'domestic',
            'requires_key': True,
            'template': '''
                <!DOCTYPE html>
                <html>
                <head>
                    <meta charset="utf-8">
                    <title>百度街景</title>
                    <style>
                        #panorama {{ height: 100%; width: 100%; }}
                        body {{ margin: 0; padding: 0; }}
                    </style>
                    <script src="https://api.map.baidu.com/api?v=3.0&ak={api_key}&type=webgl"></script>
                </head>
                <body>
                    <div id="panorama"></div>
                    <script>
                        try {{
                            var panorama = new BMapGL.Panorama('panorama', {{
                                position: new BMapGL.Point({lng}, {lat})
                            }});
                            panorama.setOptions({{
                                navigationControl: true,
                                navigationControlOptions: {{
                                    anchor: BMAP_ANCHOR_TOP_LEFT
                                }}
                            }});
                        }} catch(e) {{
                            document.body.innerHTML = '<div style="text-align:center;padding:20px;"><h3>街景加载失败</h3><p>' + e.message + '</p></div>';
                        }}
                    </script>
                </body>
                </html>
            '''
        },
        'mapillary': {
            'name': 'Mapillary',
            'region': 'international',
            'requires_key': False,
            'template': '''
                <!DOCTYPE html>
                <html>
                <head>
                    <meta charset="utf-8">
                    <title>Mapillary街景</title>
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <style>
                        #mly {{ height: 100%; width: 100%; }}
                        body {{ margin: 0; padding: 0; }}
                    </style>
                    <script src="https://unpkg.com/mapillary-js@4.1.2/dist/mapillary.js"></script>
                    <link href="https://unpkg.com/mapillary-js@4.1.2/dist/mapillary.css" rel="stylesheet"/>
                </head>
                <body>
                    <div id="mly"></div>
                    <script>
                        try {{
                            var mly = new Mapillary.Viewer(
                                'mly',
                                null,
                                null,
                                {{
                                    component: {{
                                        cover: false,
                                        direction: true,
                                        sequence: true
                                    }}
                                }}
                            );
                            
                            // 查找最近的街景
                            var clientId = 'MkJKbDA0WTJ5WjNPanFpSmFtRVo6NmE2ZjgyY2QzNmY1MmVjYg';
                            var url = 'https://graph.mapillary.com/images?access_token=' + clientId + 
                                     '&fields=id,geometry&limit=1&closest_to=' + {lng} + ',' + {lat};
                            
                            fetch(url)
                                .then(response => response.json())
                                .then(data => {{
                                    if (data.data && data.data.length > 0) {{
                                        mly.moveTo(data.data[0].id);
                                    }} else {{
                                        document.getElementById('mly').innerHTML = 
                                            '<div style="text-align:center;padding:20px;background:white;border-radius:10px;margin:20px;">' +
                                            '<h3>当前位置暂无Mapillary街景</h3>' +
                                            '<p>可以尝试使用Google街景或其他服务</p>' +
                                            '</div>';
                                    }}
                                }})
                                .catch(error => {{
                                    document.getElementById('mly').innerHTML = 
                                        '<div style="text-align:center;padding:20px;">' +
                                        '<h3>街景加载失败</h3><p>' + error.message + '</p>' +
                                        '</div>';
                                }});
                        }} catch(e) {{
                            document.body.innerHTML = '<div style="text-align:center;padding:20px;"><h3>街景加载失败</h3><p>' + e.message + '</p></div>';
                        }}
                    </script>
                </body>
                </html>
            '''
        },
        'kartaview': {
            'name': 'KartaView',
            'region': 'international',
            'requires_key': False,
            'template': '''
                <!DOCTYPE html>
                <html>
                <head>
                    <meta charset="utf-8">
                    <title>KartaView街景</title>
                    <style>
                        #kartaview {{ height: 100%; width: 100%; }}
                        body {{ margin: 0; padding: 0; }}
                    </style>
                </head>
                <body>
                    <div id="kartaview"></div>
                    <script>
                        (function() {{
                            var script = document.createElement('script');
                            script.src = 'https://api.openstreetcam.org/2.0/osc-viewer.js';
                            script.onload = function() {{
                                try {{
                                    var container = document.getElementById('kartaview');
                                    var options = {{
                                        center: [{lng}, {lat}],
                                        zoom: 17,
                                        track: true,
                                        sequence: true
                                    }};
                                    new OSC.Viewer(container, options);
                                }} catch(e) {{
                                    document.getElementById('kartaview').innerHTML = 
                                        '<div style="text-align:center;padding:20px;"><h3>街景加载失败</h3><p>' + e.message + '</p></div>';
                                }}
                            }};
                            script.onerror = function() {{
                                document.getElementById('kartaview').innerHTML = 
                                    '<div style="text-align:center;padding:20px;">' +
                                    '<h3>KartaView服务暂不可用</h3>' +
                                    '<p>请尝试使用其他街景服务</p>' +
                                    '</div>';
                            }};
                            document.head.appendChild(script);
                        }})();
                    </script>
                </body>
                </html>
            '''
        },
        'google_streetview': {
            'name': 'Google街景',
            'region': 'international',
            'requires_key': True,
            'template': '''
                <!DOCTYPE html>
                <html>
                <head>
                    <meta charset="utf-8">
                    <title>Google街景</title>
                    <style>
                        #street-view {{ height: 100%; width: 100%; }}
                        body {{ margin: 0; padding: 0; }}
                    </style>
                </head>
                <body>
                    <div id="street-view"></div>
                    <script>
                        function initStreetView() {{
                            try {{
                                var panorama = new google.maps.StreetViewPanorama(
                                    document.getElementById('street-view'), {{
                                        position: {{lat: {lat}, lng: {lng}}},
                                        pov: {{heading: 0, pitch: 0}},
                                        zoom: 1,
                                        addressControl: true,
                                        fullscreenControl: true,
                                        motionTracking: false,
                                        motionTrackingControl: true
                                    }});
                            }} catch(e) {{
                                document.getElementById('street-view').innerHTML = 
                                    '<div style="text-align:center;padding:20px;"><h3>Google街景加载失败</h3><p>' + e.message + '</p></div>';
                            }}
                        }}
                    </script>
                    <script src="https://maps.googleapis.com/maps/api/js?key={api_key}&callback=initStreetView" async defer></script>
                </body>
                </html>
            '''
        }
    }
    
    @classmethod
    def get_providers_for_region(cls, region: str, has_keys: Dict[str, bool] = None) -> List[Tuple[str, str]]:
        """获取指定区域的街景提供商"""
        providers = []
        for key, config in cls.STREET_VIEW_PROVIDERS.items():
            if config['region'] == region or config['region'] == 'all':
                if config['requires_key']:
                    if has_keys and has_keys.get(key, False):
                        providers.append((key, config['name'] + ' (需要Key)'))
                else:
                    providers.append((key, config['name']))
        return providers
    
    @classmethod
    def generate_street_view_html(cls, provider: str, lat: float, lng: float, api_key: str = '') -> str:
        """生成街景HTML"""
        config = cls.STREET_VIEW_PROVIDERS.get(provider)
        if not config:
            return cls._generate_error_html('不支持的街景提供商')
        
        if config['requires_key'] and not api_key:
            return cls._generate_no_key_html(config['name'])
        
        try:
            return config['template'].format(lat=lat, lng=lng, api_key=api_key)
        except Exception as e:
            return cls._generate_error_html(f'生成街景失败: {str(e)}')
    
    @classmethod
    def _generate_error_html(cls, message: str) -> str:
        """生成错误信息HTML"""
        return f'''
        <!DOCTYPE html>
        <html>
        <head><meta charset="utf-8"></head>
        <body style="display:flex;justify-content:center;align-items:center;height:100%;margin:0;background:#f0f0f0;">
            <div style="text-align:center;padding:20px;background:white;border-radius:10px;box-shadow:0 2px 10px rgba(0,0,0,0.1);">
                <h3>错误</h3>
                <p>{message}</p>
            </div>
        </body>
        </html>
        '''
    
    @classmethod
    def _generate_no_key_html(cls, provider_name: str) -> str:
        """生成缺少API Key的HTML"""
        return f'''
        <!DOCTYPE html>
        <html>
        <head><meta charset="utf-8"></head>
        <body style="display:flex;justify-content:center;align-items:center;height:100%;margin:0;background:#f0f0f0;">
            <div style="text-align:center;padding:20px;background:white;border-radius:10px;box-shadow:0 2px 10px rgba(0,0,0,0.1);">
                <h3>{provider_name}需要API Key</h3>
                <p>请在设置中配置{provider_name}的API Key</p>
                <p>或使用免费的街景服务</p>
            </div>
        </body>
        </html>
        '''


class MapStyleWidget(QWidget):
    """地图样式选择控件"""
    
    style_changed = Signal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMaximumWidth(200)
        self._init_ui()
    
    def _init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # 标题
        title_label = QLabel("地图样式")
        title_label.setFont(QFont("Arial", 10, QFont.Bold))
        layout.addWidget(title_label)
        
        # 样式列表
        self.style_list = QListWidget()
        self.style_list.setIconSize(QSize(32, 32))
        
        styles = EnhancedMapTileManager.get_style_names()
        for style_key, style_name in styles:
            item = QListWidgetItem(style_name)
            item.setData(Qt.UserRole, style_key)
            item.setToolTip(f"使用 {style_name} 地图样式")
            self.style_list.addItem(item)
        
        self.style_list.setCurrentRow(0)
        self.style_list.currentItemChanged.connect(self._on_style_changed)
        
        layout.addWidget(self.style_list)
        
        # 透明度控制
        opacity_layout = QHBoxLayout()
        opacity_layout.addWidget(QLabel("透明度:"))
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(50, 100)
        self.opacity_slider.setValue(100)
        self.opacity_slider.setTickPosition(QSlider.TicksBelow)
        self.opacity_slider.setTickInterval(10)
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        opacity_layout.addWidget(self.opacity_slider)
        
        self.opacity_label = QLabel("100%")
        opacity_layout.addWidget(self.opacity_label)
        
        layout.addLayout(opacity_layout)
    
    def _on_style_changed(self, current, previous):
        """样式改变"""
        if current:
            style_key = current.data(Qt.UserRole)
            self.style_changed.emit(style_key)
    
    def _on_opacity_changed(self, value):
        """透明度改变"""
        self.opacity_label.setText(f"{value}%")
        # 这里可以实现地图透明度控制
    
    def get_current_style(self) -> str:
        """获取当前选中的样式"""
        current_item = self.style_list.currentItem()
        if current_item:
            return current_item.data(Qt.UserRole)
        return 'openstreetmap'


class EnhancedMapWidget(QWebEngineView):
    """增强的地图显示组件"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_location = None
        self.current_style = 'openstreetmap'
        self.map_ready = False
        self.setMinimumSize(400, 300)
        self._init_map()
    
    def _init_map(self):
        """初始化地图"""
        self.load_default_map()
    
    def load_default_map(self):
        """加载默认地图"""
        style_config = EnhancedMapTileManager.get_style_config(self.current_style)
        
        # 处理子域名
        subdomain_js = ''
        if style_config['subdomains']:
            subdomain_list = ','.join([f"'{s}'" for s in style_config['subdomains']])
            subdomain_js = f"subdomains: [{subdomain_list}],"
        
        html = f'''
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{style_config['name']}</title>
            <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
            <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
            <style>
                #map {{ height: 100vh; width: 100%; }}
                body {{ margin: 0; padding: 0; }}
                .leaflet-control-layers {{ display: none; }}
                .map-info {{
                    position: absolute;
                    bottom: 10px;
                    right: 10px;
                    background: rgba(255,255,255,0.8);
                    padding: 5px 10px;
                    border-radius: 4px;
                    font-size: 12px;
                    z-index: 1000;
                }}
            </style>
        </head>
        <body>
            <div id="map"></div>
            <div class="map-info" id="mapInfo"></div>
            <script>
                var map = null;
                var marker = null;
                var currentLayer = null;
                
                function initMap() {{
                    map = L.map('map', {{
                        center: [39.9042, 116.4074],
                        zoom: 13,
                        zoomControl: true,
                        attributionControl: true
                    }});
                    
                    // 添加默认图层
                    setMapLayer('{self.current_style}');
                    
                    // 添加比例尺
                    L.control.scale({{
                        imperial: false,
                        position: 'bottomleft'
                    }}).addTo(map);
                    
                    // 监听移动事件更新信息
                    map.on('moveend', function() {{
                        updateMapInfo();
                    }});
                    
                    updateMapInfo();
                    window.mapReady = true;
                }}
                
                function setMapLayer(styleKey) {{
                    if (currentLayer) {{
                        map.removeLayer(currentLayer);
                    }}
                    
                    var styles = {json.dumps(EnhancedMapTileManager.MAP_STYLES)};
                    var config = styles[styleKey];
                    
                    if (config) {{
                        currentLayer = L.tileLayer(config.url, {{
                            maxZoom: config.max_zoom,
                            attribution: config.attribution,
                            {subdomain_js}
                        }}).addTo(map);
                    }}
                }}
                
                function setLocation(lat, lng, zoom) {{
                    if (map) {{
                        map.setView([lat, lng], zoom || 15);
                        
                        if (marker) {{
                            map.removeLayer(marker);
                        }}
                        
                        marker = L.marker([lat, lng], {{
                            draggable: false,
                            title: '目标位置'
                        }}).addTo(map);
                        
                        marker.bindPopup('目标位置<br>' + lat.toFixed(6) + ', ' + lng.toFixed(6)).openPopup();
                    }}
                }}
                
                function updateMapInfo() {{
                    if (map) {{
                        var center = map.getCenter();
                        var zoom = map.getZoom();
                        document.getElementById('mapInfo').innerHTML = 
                            '坐标: ' + center.lat.toFixed(5) + ', ' + center.lng.toFixed(5) + 
                            ' | 缩放: ' + zoom;
                    }}
                }}
                
                // 初始化地图
                if (document.readyState === 'loading') {{
                    document.addEventListener('DOMContentLoaded', initMap);
                }} else {{
                    initMap();
                }}
            </script>
        </body>
        </html>
        '''
        
        self.setHtml(html)
        self.map_ready = True
    
    def change_style(self, style_key: str):
        """更改地图样式"""
        self.current_style = style_key
        style_config = EnhancedMapTileManager.get_style_config(style_key)
        
        js_code = f'''
            if (window.mapReady && typeof map !== 'undefined') {{
                setMapLayer('{style_key}');
            }}
        '''
        self.page().runJavaScript(js_code)
    
    def show_location(self, lat: float, lng: float, zoom: int = 15):
        """显示指定位置"""
        self.current_location = (lat, lng)
        
        js_code = f'''
            if (window.mapReady && typeof map !== 'undefined') {{
                setLocation({lat}, {lng}, {zoom});
            }}
        '''
        self.page().runJavaScript(js_code)


class EnhancedStreetViewWidget(QWebEngineView):
    """增强的街景显示组件"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_provider = 'mapillary'
        self.setMinimumSize(400, 300)
        self._load_default_view()
    
    def _load_default_view(self):
        """加载默认街景视图"""
        html = '''
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>街景视图</title>
            <style>
                body {
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    height: 100vh;
                    margin: 0;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    font-family: 'Microsoft YaHei', Arial, sans-serif;
                }
                .welcome-container {
                    text-align: center;
                    color: white;
                    padding: 40px;
                    background: rgba(255, 255, 255, 0.1);
                    border-radius: 20px;
                    backdrop-filter: blur(10px);
                    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
                }
                .welcome-container h2 {
                    margin-bottom: 20px;
                    font-size: 24px;
                }
                .welcome-container p {
                    margin: 10px 0;
                    font-size: 14px;
                    opacity: 0.9;
                }
                .feature-list {
                    text-align: left;
                    margin: 20px auto;
                    max-width: 300px;
                }
                .feature-item {
                    margin: 8px 0;
                    padding: 5px 10px;
                    background: rgba(255, 255, 255, 0.1);
                    border-radius: 5px;
                }
            </style>
        </head>
        <body>
            <div class="welcome-container">
                <h2>🌍 街景视图</h2>
                <div class="feature-list">
                    <div class="feature-item">📷 支持多种街景服务</div>
                    <div class="feature-item">🇨🇳 国内：百度街景</div>
                    <div class="feature-item">🌏 国外：Mapillary（免费）</div>
                    <div class="feature-item">🗺️ KartaView（免费）</div>
                    <div class="feature-item">🔍 Google街景（需Key）</div>
                </div>
                <p>输入地址并搜索以查看街景</p>
            </div>
        </body>
        </html>
        '''
        self.setHtml(html)
    
    def show_street_view(self, lat: float, lng: float, provider: str = 'mapillary',
                        api_key: str = ''):
        """显示街景"""
        self.current_provider = provider
        html = EnhancedStreetViewManager.generate_street_view_html(
            provider, lat, lng, api_key
        )
        self.setHtml(html)


class MapControlsWidget(QWidget):
    """地图控制面板"""
    
    style_changed = Signal(str)
    provider_changed = Signal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMaximumWidth(220)
        self._init_ui()
    
    def _init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        
        # 地图样式选择
        style_group = QGroupBox("地图样式")
        style_layout = QVBoxLayout(style_group)
        
        self.style_combo = QComboBox()
        styles = EnhancedMapTileManager.get_style_names()
        for style_key, style_name in styles:
            self.style_combo.addItem(style_name, style_key)
        
        self.style_combo.currentIndexChanged.connect(self._on_style_changed)
        style_layout.addWidget(self.style_combo)
        
        layout.addWidget(style_group)
        
        # 街景提供商选择
        street_group = QGroupBox("街景服务")
        street_layout = QVBoxLayout(street_group)
        
        self.provider_combo = QComboBox()
        self._update_providers('international')
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        street_layout.addWidget(self.provider_combo)
        
        layout.addWidget(street_group)
        
        # 信息显示
        info_group = QGroupBox("位置信息")
        info_layout = QVBoxLayout(info_group)
        
        self.coord_label = QLabel("坐标: 未定位")
        self.coord_label.setWordWrap(True)
        info_layout.addWidget(self.coord_label)
        
        self.zoom_label = QLabel("缩放级别: -")
        info_layout.addWidget(self.zoom_label)
        
        layout.addWidget(info_group)
        
        layout.addStretch()
    
    def _update_providers(self, region: str):
        """更新街景提供商列表"""
        self.provider_combo.clear()
        
        # 获取是否有API Key
        has_keys = {
            'baidu': bool(self._get_api_key('baidu')),
            'google_streetview': bool(self._get_api_key('google'))
        }
        
        providers = EnhancedStreetViewManager.get_providers_for_region(region, has_keys)
        for provider_key, provider_name in providers:
            self.provider_combo.addItem(provider_name, provider_key)
    
    def _get_api_key(self, service: str) -> str:
        """获取API Key（需要从数据库获取）"""
        # 这里简化处理，实际应从数据库获取
        return ''
    
    def _on_style_changed(self, index):
        """样式改变"""
        style_key = self.style_combo.currentData()
        if style_key:
            self.style_changed.emit(style_key)
    
    def _on_provider_changed(self, index):
        """提供商改变"""
        provider_key = self.provider_combo.currentData()
        if provider_key:
            self.provider_changed.emit(provider_key)
    
    def update_location_info(self, lat: float = None, lng: float = None, zoom: int = None):
        """更新位置信息"""
        if lat and lng:
            self.coord_label.setText(f"坐标: {lat:.6f}, {lng:.6f}")
        if zoom:
            self.zoom_label.setText(f"缩放级别: {zoom}")
    
    def set_region(self, region: str):
        """设置区域"""
        self._update_providers(region)


# 以下是之前代码中的其他类，保持不变
# DatabaseManager, SearchWorker, BackupWorker, RestoreWorker, 
# BackupDialog, SettingsDialog, MainWindow等类继续使用之前的实现


class DatabaseManager:
    """数据库管理器 - 统一管理所有数据库操作"""

    def __init__(self, db_path: str = "app_data.db"):
        self.db_path = db_path
        self.backup_dir = Path("backups")
        self.backup_dir.mkdir(exist_ok=True)
        self.max_backups = 30
        self.connection = None
        self.mutex = QMutex()
        self._initialize_database()
        self._load_settings()

    def _load_settings(self):
        """加载数据库设置"""
        settings = QSettings("MapLocator", "DatabaseSettings")
        self.max_backups = int(settings.value("max_backups", 30))

    def _save_settings(self):
        """保存数据库设置"""
        settings = QSettings("MapLocator", "DatabaseSettings")
        settings.setValue("max_backups", self.max_backups)

    def _initialize_database(self):
        """初始化数据库结构"""
        self.connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self._create_tables()

    def _create_tables(self):
        """创建数据库表"""
        cursor = self.connection.cursor()
        cursor.executescript('''
            CREATE TABLE IF NOT EXISTS location_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                address TEXT NOT NULL,
                latitude REAL,
                longitude REAL,
                location_type TEXT DEFAULT 'domestic',
                search_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                search_count INTEGER DEFAULT 1,
                map_style TEXT DEFAULT 'openstreetmap',
                street_provider TEXT DEFAULT 'mapillary'
            );

            CREATE TABLE IF NOT EXISTS api_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_name TEXT UNIQUE NOT NULL,
                api_key TEXT,
                api_secret TEXT,
                additional_params TEXT,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS backup_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                backup_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                backup_type TEXT CHECK(backup_type IN ('auto', 'manual', 'rollback')),
                file_name TEXT NOT NULL,
                file_size INTEGER,
                db_version TEXT,
                date_range_start TEXT,
                date_range_end TEXT,
                record_count INTEGER
            );

            CREATE INDEX IF NOT EXISTS idx_location_search 
            ON location_history(address, search_time DESC);

            CREATE INDEX IF NOT EXISTS idx_backup_time 
            ON backup_records(backup_time DESC);
        ''')
        self.connection.commit()

    # 其他方法保持不变...


class SearchWorker(QThread):
    """搜索工作线程"""
    search_completed = Signal(dict)
    search_failed = Signal(str)
    progress_updated = Signal(int)

    def __init__(self, address: str, location_type: str, db_manager: DatabaseManager):
        super().__init__()
        self.address = address
        self.location_type = location_type
        self.db_manager = db_manager
        self._is_running = True

    def run(self):
        try:
            self.progress_updated.emit(10)
            coordinates = self._geocode_address()
            self.progress_updated.emit(50)

            if coordinates:
                self.db_manager.add_location_record(
                    self.address,
                    coordinates['lat'],
                    coordinates['lng'],
                    self.location_type
                )
                self.progress_updated.emit(80)

                result = {
                    'address': self.address,
                    'lat': coordinates['lat'],
                    'lng': coordinates['lng'],
                    'location_type': self.location_type,
                    'display_name': coordinates.get('display_name', self.address)
                }
                self.progress_updated.emit(100)
                self.search_completed.emit(result)
            else:
                self.search_failed.emit("无法解析该地址的坐标信息")

        except Exception as e:
            logger.error(f"搜索失败: {e}")
            self.search_failed.emit(f"搜索出错: {str(e)}")

    def _geocode_address(self) -> Optional[Dict]:
        """地址解析 - 增强版，支持多种服务"""
        methods = []
        
        if self.location_type == 'domestic':
            # 国内优先使用高德，然后使用Nominatim作为备用
            methods.append(self._amap_geocode)
            methods.append(self._nominatim_geocode)
        else:
            # 国外优先使用Nominatim，然后可以使用其他免费服务
            methods.append(self._nominatim_geocode)
            methods.append(self._photon_geocode)
        
        for method in methods:
            try:
                result = method()
                if result:
                    return result
            except Exception as e:
                logger.debug(f"{method.__name__} 失败: {e}")
                continue
        
        return None

    def _amap_geocode(self) -> Optional[Dict]:
        """高德地图地址解析"""
        try:
            settings = self.db_manager.get_api_settings('amap')
            if settings and settings.get('api_key'):
                import requests
                api_key = settings['api_key']
                url = "https://restapi.amap.com/v3/geocode/geo"
                params = {
                    'key': api_key,
                    'address': self.address,
                    'output': 'JSON'
                }

                response = requests.get(url, params=params, timeout=10)
                data = response.json()

                if data['status'] == '1' and data['geocodes']:
                    location = data['geocodes'][0]['location'].split(',')
                    return {
                        'lat': float(location[1]),
                        'lng': float(location[0]),
                        'display_name': data['geocodes'][0]['formatted_address']
                    }
        except Exception as e:
            logger.error(f"高德地理编码失败: {e}")
        return None

    def _nominatim_geocode(self) -> Optional[Dict]:
        """Nominatim地理编码"""
        try:
            import requests
            url = "https://nominatim.openstreetmap.org/search"
            params = {
                'q': self.address,
                'format': 'json',
                'limit': 1,
                'accept-language': 'zh'
            }
            headers = {
                'User-Agent': 'MapLocatorApp/1.0'
            }

            response = requests.get(url, params=params, headers=headers, timeout=10)
            data = response.json()

            if data:
                return {
                    'lat': float(data[0]['lat']),
                    'lng': float(data[0]['lon']),
                    'display_name': data[0].get('display_name', self.address)
                }
        except Exception as e:
            logger.error(f"Nominatim地理编码失败: {e}")
        return None

    def _photon_geocode(self) -> Optional[Dict]:
        """Photon地理编码（基于OpenStreetMap）"""
        try:
            import requests
            url = "https://photon.komoot.io/api/"
            params = {
                'q': self.address,
                'limit': 1,
                'lang': 'zh'
            }

            response = requests.get(url, params=params, timeout=10)
            data = response.json()

            if data.get('features'):
                feature = data['features'][0]
                coords = feature['geometry']['coordinates']
                return {
                    'lat': float(coords[1]),
                    'lng': float(coords[0]),
                    'display_name': feature['properties'].get('name', self.address)
                }
        except Exception as e:
            logger.error(f"Photon地理编码失败: {e}")
        return None

    def stop(self):
        self._is_running = False


class MainWindow(QMainWindow):
    """主窗口"""

    def __init__(self):
        super().__init__()
        self.db_manager = DatabaseManager()
        self.setWindowTitle("地址定位与街景查看系统 - 增强版")
        self.setMinimumSize(1200, 800)

        self._load_icon()
        self._init_ui()
        self._load_app_settings()
        self._start_auto_backup()

        self.statusBar().showMessage("系统就绪 | 支持多种地图样式和街景服务", 3000)

    def _load_icon(self):
        """加载图标"""
        icon_path = Path("icon.ico")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

    def _init_ui(self):
        """初始化UI"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        # 工具栏
        toolbar = QToolBar()
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        
        # 搜索区域
        search_widget = QWidget()
        search_layout = QHBoxLayout(search_widget)
        search_layout.setContentsMargins(0, 0, 0, 0)

        search_layout.addWidget(QLabel("地址:"))
        self.address_input = QLineEdit()
        self.address_input.setPlaceholderText("输入地址进行搜索（支持中英文）...")
        self.address_input.returnPressed.connect(self._search_location)
        search_layout.addWidget(self.address_input, 2)

        search_layout.addWidget(QLabel("区域:"))
        self.location_type_combo = QComboBox()
        self.location_type_combo.addItems(['国内', '国外'])
        self.location_type_combo.currentTextChanged.connect(self._on_region_changed)
        search_layout.addWidget(self.location_type_combo)

        self.search_btn = QPushButton("🔍 搜索")
        self.search_btn.clicked.connect(self._search_location)
        search_layout.addWidget(self.search_btn)

        main_layout.addWidget(search_widget)

        # 地图和街景分割区域
        content_splitter = QSplitter(Qt.Horizontal)
        
        # 左侧：地图和控制面板
        left_panel = QWidget()
        left_layout = QHBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        # 地图视图
        map_container = QWidget()
        map_layout = QVBoxLayout(map_container)
        map_layout.setContentsMargins(0, 0, 0, 0)
        
        map_label = QLabel("📍 地图视图")
        map_label.setStyleSheet("font-weight: bold; padding: 5px; background: #f8f9fa; border-radius: 3px;")
        map_layout.addWidget(map_label)
        
        self.map_view = EnhancedMapWidget()
        self.map_view.load_default_map()
        map_layout.addWidget(self.map_view)
        
        left_layout.addWidget(map_container, 1)
        
        # 地图控制面板
        self.map_controls = MapControlsWidget()
        self.map_controls.style_changed.connect(self._on_map_style_changed)
        self.map_controls.provider_changed.connect(self._on_street_provider_changed)
        left_layout.addWidget(self.map_controls)
        
        content_splitter.addWidget(left_panel)
        
        # 右侧：街景视图
        street_container = QWidget()
        street_layout = QVBoxLayout(street_container)
        street_layout.setContentsMargins(0, 0, 0, 0)
        
        street_label = QLabel("🖼️ 街景视图")
        street_label.setStyleSheet("font-weight: bold; padding: 5px; background: #f8f9fa; border-radius: 3px;")
        street_layout.addWidget(street_label)
        
        self.street_view = EnhancedStreetViewWidget()
        street_layout.addWidget(self.street_view)
        
        content_splitter.addWidget(street_container)
        
        content_splitter.setSizes([600, 600])
        main_layout.addWidget(content_splitter, 1)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumHeight(20)
        main_layout.addWidget(self.progress_bar)

        # 状态栏
        self.setStatusBar(QStatusBar())

        # 菜单栏
        self._create_menu_bar()

    def _create_menu_bar(self):
        """创建菜单栏"""
        menubar = self.menuBar()

        # 文件菜单
        file_menu = menubar.addMenu("文件(&F)")
        
        backup_action = QAction("数据库备份管理(&B)", self)
        backup_action.triggered.connect(self._open_backup_dialog)
        file_menu.addAction(backup_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("退出(&Q)", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # 视图菜单
        view_menu = menubar.addMenu("视图(&V)")
        
        # 地图样式子菜单
        styles_menu = view_menu.addMenu("地图样式")
        styles = EnhancedMapTileManager.get_style_names()
        for style_key, style_name in styles:
            style_action = QAction(style_name, self)
            style_action.triggered.connect(lambda checked, key=style_key: self._on_map_style_changed(key))
            styles_menu.addAction(style_action)
        
        view_menu.addSeparator()
        
        # 街景服务子菜单
        street_menu = view_menu.addMenu("街景服务")
        self._update_street_menu(street_menu)

        # 工具菜单
        tools_menu = menubar.addMenu("工具(&T)")
        
        settings_action = QAction("设置(&S)", self)
        settings_action.triggered.connect(self._open_settings_dialog)
        tools_menu.addAction(settings_action)
        
        clear_history_action = QAction("清除搜索历史(&C)", self)
        clear_history_action.triggered.connect(self._clear_history)
        tools_menu.addAction(clear_history_action)

        # 帮助菜单
        help_menu = menubar.addMenu("帮助(&H)")
        
        about_action = QAction("关于(&A)", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _update_street_menu(self, street_menu):
        """更新街景菜单"""
        street_menu.clear()
        region = 'domestic' if self.location_type_combo.currentText() == '国内' else 'international'
        has_keys = self._check_api_keys()
        
        providers = EnhancedStreetViewManager.get_providers_for_region(region, has_keys)
        for provider_key, provider_name in providers:
            provider_action = QAction(provider_name, self)
            provider_action.triggered.connect(lambda checked, key=provider_key: self._on_street_provider_changed(key))
            street_menu.addAction(provider_action)

    def _check_api_keys(self) -> Dict[str, bool]:
        """检查API Key配置"""
        has_keys = {}
        for service in ['baidu', 'google']:
            settings = self.db_manager.get_api_settings(service)
            has_keys[service] = bool(settings and settings.get('api_key'))
            has_keys[f'{service}_streetview'] = has_keys[service]
        return has_keys

    def _search_location(self):
        """搜索位置"""
        address = self.address_input.text().strip()
        if not address:
            self.statusBar().showMessage("请输入地址", 3000)
            return

        location_type = 'domestic' if self.location_type_combo.currentText() == '国内' else 'international'

        # 显示进度条
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.search_btn.setEnabled(False)

        # 创建搜索线程
        self.search_worker = SearchWorker(address, location_type, self.db_manager)
        self.search_worker.progress_updated.connect(self.progress_bar.setValue)
        self.search_worker.search_completed.connect(self._on_search_completed)
        self.search_worker.search_failed.connect(self._on_search_failed)
        self.search_worker.start()

    def _on_search_completed(self, result: Dict):
        """搜索完成"""
        self.progress_bar.setVisible(False)
        self.search_btn.setEnabled(True)

        # 更新地图
        self.map_view.show_location(result['lat'], result['lng'])

        # 获取当前选择的街景提供商和API Key
        provider = self.map_controls.provider_combo.currentData() or 'mapillary'
        api_key = self._get_api_key_for_provider(provider)

        # 更新街景
        self.street_view.show_street_view(result['lat'], result['lng'], provider, api_key)

        # 更新控制面板信息
        self.map_controls.update_location_info(result['lat'], result['lng'])

        self.statusBar().showMessage(f"✅ 已定位: {result['display_name']}", 5000)

    def _on_search_failed(self, error: str):
        """搜索失败"""
        self.progress_bar.setVisible(False)
        self.search_btn.setEnabled(True)
        self.statusBar().showMessage(f"❌ 搜索失败: {error}", 5000)

    def _on_map_style_changed(self, style_key: str):
        """地图样式改变"""
        self.map_view.change_style(style_key)
        style_name = EnhancedMapTileManager.get_style_config(style_key)['name']
        self.statusBar().showMessage(f"地图样式: {style_name}", 3000)

    def _on_street_provider_changed(self, provider_key: str):
        """街景提供商改变"""
        if self.map_view.current_location:
            lat, lng = self.map_view.current_location
            api_key = self._get_api_key_for_provider(provider_key)
            self.street_view.show_street_view(lat, lng, provider_key, api_key)
        
        provider_name = EnhancedStreetViewManager.STREET_VIEW_PROVIDERS.get(provider_key, {}).get('name', provider_key)
        self.statusBar().showMessage(f"街景服务: {provider_name}", 3000)

    def _on_region_changed(self, region: str):
        """区域改变"""
        self.map_controls.set_region('domestic' if region == '国内' else 'international')

    def _get_api_key_for_provider(self, provider: str) -> str:
        """获取街景提供商的API Key"""
        if provider == 'baidu':
            settings = self.db_manager.get_api_settings('baidu')
            return settings.get('api_key', '') if settings else ''
        elif provider == 'google_streetview':
            settings = self.db_manager.get_api_settings('google')
            return settings.get('api_key', '') if settings else ''
        return ''

    def _open_backup_dialog(self):
        """打开备份管理对话框"""
        dialog = BackupDialog(self.db_manager, self)
        dialog.exec()
        self.statusBar().showMessage("数据库连接已刷新", 3000)

    def _open_settings_dialog(self):
        """打开设置对话框"""
        dialog = SettingsDialog(self.db_manager, self)
        if dialog.exec() == QDialog.Accepted:
            self.statusBar().showMessage("设置已保存", 3000)

    def _clear_history(self):
        """清除搜索历史"""
        reply = QMessageBox.question(
            self, "确认",
            "确定要清除所有搜索历史吗？",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            cursor = self.db_manager.get_connection().cursor()
            cursor.execute('DELETE FROM location_history')
            self.db_manager.get_connection().commit()
            self.statusBar().showMessage("搜索历史已清除", 3000)

    def _show_about(self):
        """显示关于对话框"""
        QMessageBox.about(
            self,
            "关于",
            "地址定位与街景查看系统 v2.0\n\n"
            "功能：\n"
            "• 输入地址查看地图位置和街景\n"
            "• 支持多种地图样式\n"
            "• 支持多种街景服务\n\n"
            "地图样式：\n"
            "• OpenStreetMap\n"
            "• CartoDB (亮色/暗色)\n"
            "• Stamen (Terrain/Toner/Watercolor)\n"
            "• ESRI卫星图\n"
            "• Wikimedia Maps\n\n"
            "街景服务：\n"
            "• 国内：百度街景\n"
            "• 国外：Mapillary（免费）\n"
            "• KartaView（免费）\n"
            "• Google街景\n\n"
            "© 2024 MapLocator Enhanced"
        )

    def _start_auto_backup(self):
        """启动自动备份"""
        auto_backup = BackupWorker(self.db_manager, 'auto')
        auto_backup.backup_completed.connect(
            lambda path: self.statusBar().showMessage(f"自动备份完成: {path}", 3000)
        )
        auto_backup.backup_failed.connect(
            lambda error: logger.error(f"自动备份失败: {error}")
        )
        auto_backup.start()

        self.backup_timer = QTimer()
        self.backup_timer.timeout.connect(
            lambda: BackupWorker(self.db_manager, 'auto').start()
        )
        self.backup_timer.start(24 * 60 * 60 * 1000)

    def _load_app_settings(self):
        """加载应用设置"""
        settings = QSettings("MapLocator", "MainWindow")
        geometry = settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        state = settings.value("windowState")
        if state:
            self.restoreState(state)

        debug_mode = self.db_manager.get_app_setting('debug_mode', 'false')
        global DEBUG_MODE
        DEBUG_MODE = debug_mode.lower() == 'true'

    def closeEvent(self, event):
        """关闭事件"""
        settings = QSettings("MapLocator", "MainWindow")
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("windowState", self.saveState())

        self.db_manager.save_app_setting(
            'location_type',
            self.location_type_combo.currentText()
        )

        if self.db_manager.connection:
            self.db_manager.connection.close()

        event.accept()


def main():
    """主函数"""
    try:
        app = QApplication(sys.argv)
        app.setApplicationName("MapLocator")
        app.setOrganizationName("MapLocator")
        app.setStyle('Fusion')

        window = MainWindow()
        window.show()

        sys.exit(app.exec())

    except Exception as e:
        logger.error(f"程序启动失败: {e}")
        if DEBUG_MODE:
            raise
        else:
            app = QApplication.instance()
            if app:
                QMessageBox.critical(None, "错误", f"程序启动失败: {str(e)}")
            sys.exit(1)


if __name__ == "__main__":
    main()