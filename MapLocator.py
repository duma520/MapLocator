#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
地图街景查看器 - 国内外免费服务大全版
整合所有免注册的地图和街景服务
"""

import sys
import os
import json
import sqlite3
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
import logging
import socket
import time
import warnings

warnings.filterwarnings('ignore')

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox,
    QStatusBar, QProgressBar, QMessageBox,
    QDialog, QSplitter, QGroupBox, QCheckBox, QSpinBox,
    QTextEdit, QScrollArea
)
from PySide6.QtCore import Qt, QThread, Signal, QSettings, QMutex, QUrl
from PySide6.QtGui import QIcon
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtNetwork import QNetworkProxy

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


class ProxyManager:
    def __init__(self):
        self.enabled = True
        self.host = "127.0.0.1"
        self.port = 20808
        self._load()
    
    def _load(self):
        try:
            s = QSettings("MapLocator", "Proxy")
            self.enabled = s.value("enabled", "true") == "true"
            self.host = s.value("host", "127.0.0.1")
            self.port = int(s.value("port", 20808))
        except: pass
    
    def save(self):
        s = QSettings("MapLocator", "Proxy")
        s.setValue("enabled", str(self.enabled).lower())
        s.setValue("host", self.host)
        s.setValue("port", self.port)
    
    def get_proxies(self):
        if not self.enabled: return None
        u = f"http://{self.host}:{self.port}"
        return {'http': u, 'https': u}


proxy = ProxyManager()


class MapTileProviders:
    """地图瓦片服务商大全"""
    
    # 国内免费（无需API Key）
    DOMESTIC_FREE = {
        # 高德地图（旧版瓦片，无需Key）
        'amap_normal': {
            'name': '高德地图(国内)',
            'url': 'https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}',
            'attribution': '© 高德地图',
            'max_zoom': 18,
            'subdomains': ['1', '2', '3', '4'],
            'region': 'domestic'
        },
        'amap_satellite': {
            'name': '高德卫星图(国内)',
            'url': 'https://webst0{s}.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}',
            'attribution': '© 高德地图',
            'max_zoom': 18,
            'subdomains': ['1', '2', '3', '4'],
            'region': 'domestic'
        },
        # 天地图（国家测绘局，免费）
        'tianditu_normal': {
            'name': '天地图(国内)',
            'url': 'https://t{s}.tianditu.gov.cn/vec_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=vec&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&tk=',
            'attribution': '© 天地图',
            'max_zoom': 18,
            'subdomains': ['0', '1', '2', '3', '4', '5', '6', '7'],
            'region': 'domestic'
        },
        'tianditu_satellite': {
            'name': '天地图卫星(国内)',
            'url': 'https://t{s}.tianditu.gov.cn/img_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=img&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&tk=',
            'attribution': '© 天地图',
            'max_zoom': 18,
            'subdomains': ['0', '1', '2', '3', '4', '5', '6', '7'],
            'region': 'domestic'
        },
        # 腾讯地图
        'tencent_normal': {
            'name': '腾讯地图(国内)',
            'url': 'https://rt{s}.map.gtimg.com/tile?z={z}&x={x}&y={y}&type=vector&styleid=0',
            'attribution': '© 腾讯地图',
            'max_zoom': 18,
            'subdomains': ['0', '1', '2', '3'],
            'region': 'domestic'
        },
    }
    
    # 国外免费
    INTERNATIONAL_FREE = {
        'cartodb_light': {
            'name': 'CartoDB Light',
            'url': 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png',
            'attribution': '© CartoDB',
            'max_zoom': 19,
            'subdomains': ['a', 'b', 'c', 'd'],
            'region': 'international'
        },
        'cartodb_dark': {
            'name': 'CartoDB Dark',
            'url': 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',
            'attribution': '© CartoDB',
            'max_zoom': 19,
            'subdomains': ['a', 'b', 'c', 'd'],
            'region': 'international'
        },
        'esri_satellite': {
            'name': 'ESRI 卫星图',
            'url': 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
            'attribution': '© Esri',
            'max_zoom': 19,
            'subdomains': [],
            'region': 'international'
        },
        'esri_street': {
            'name': 'ESRI 街道图',
            'url': 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}',
            'attribution': '© Esri',
            'max_zoom': 19,
            'subdomains': [],
            'region': 'international'
        },
        'osm': {
            'name': 'OpenStreetMap',
            'url': 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
            'attribution': '© OSM',
            'max_zoom': 19,
            'subdomains': [],
            'region': 'international'
        },
        'wikimedia': {
            'name': 'Wikimedia',
            'url': 'https://maps.wikimedia.org/osm-intl/{z}/{x}/{y}.png',
            'attribution': '© Wikimedia',
            'max_zoom': 19,
            'subdomains': [],
            'region': 'international'
        },
    }
    
    @classmethod
    def get_all(cls) -> Dict:
        all_tiles = {}
        all_tiles.update(cls.DOMESTIC_FREE)
        all_tiles.update(cls.INTERNATIONAL_FREE)
        return all_tiles
    
    @classmethod
    def get_by_region(cls, region='all') -> List[Tuple[str, str]]:
        result = []
        if region in ('all', 'domestic'):
            for k, v in cls.DOMESTIC_FREE.items():
                result.append((k, f"[国内] {v['name']}"))
        if region in ('all', 'international'):
            for k, v in cls.INTERNATIONAL_FREE.items():
                result.append((k, f"[国外] {v['name']}"))
        return result


class StreetViewProviders:
    """街景服务商"""
    
    @staticmethod
    def mapillary(lat, lng):
        """Mapillary - 国外街景"""
        return f'''<!DOCTYPE html><html><head><meta charset="utf-8">
<style>*{{margin:0;padding:0;}}html,body,#v{{width:100%;height:100%;}}
#v{{display:flex;justify-content:center;align-items:center;background:#f0f0f0;font-family:Arial;}}</style></head>
<body><div id="v"><div style="text-align:center;">
<p>加载Mapillary...</p><p style="color:#999;">{lat:.4f}, {lng:.4f}</p></div></div>
<script>
(function(){{
var t='MLY|44415055e28e08c1f1d01dfcd9a4e2bb';
fetch('https://graph.mapillary.com/images?access_token='+t+'&fields=id&limit=3&closest_to='+{lng}+','+{lat})
.then(r=>r.json()).then(d=>{{
if(d.data&&d.data.length>0)document.getElementById('v').innerHTML='<iframe src="https://www.mapillary.com/embed?image_key='+d.data[0].id+'" style="width:100%;height:100%;border:none;"></iframe>';
else document.getElementById('v').innerHTML='<div style="text-align:center;padding:20px;background:#fff3cd;border-radius:10px;"><h3>此处无街景</h3></div>';
}}).catch(e=>{{document.getElementById('v').innerHTML='<div style="text-align:center;padding:20px;background:#fff3cd;border-radius:10px;"><h3>加载失败</h3><p>'+e.message+'</p></div>';}});
}})();</script></body></html>'''
    
    @staticmethod
    def baidu_panorama(lat, lng):
        """百度全景（通过网页版，无需API Key）"""
        # 使用百度地图网页版的全景功能
        return f'''<!DOCTYPE html><html><head><meta charset="utf-8">
<style>*{{margin:0;padding:0;}}html,body,#v{{width:100%;height:100%;}}</style></head>
<body><div id="v"></div>
<script>
(function(){{
    // 百度全景URL格式
    var url='https://map.baidu.com/@'+{lng}+','+{lat}+',21z#panoid=01002200001308301448367575K&panotype=street&heading=0&pitch=0';
    document.getElementById('v').innerHTML='<iframe src="'+url+'" style="width:100%;height:100%;border:none;"></iframe>';
}})();
</script></body></html>'''
    
    @staticmethod
    def tencent_streetview(lat, lng):
        """腾讯街景（通过网页版）"""
        return f'''<!DOCTYPE html><html><head><meta charset="utf-8">
<style>*{{margin:0;padding:0;}}html,body,#v{{width:100%;height:100%;}}</style></head>
<body><div id="v"></div>
<script>
(function(){{
    // 腾讯地图街景URL
    var url='https://map.qq.com/#pano=10041001150729120357400&heading=0&pitch=0&zoom=1';
    document.getElementById('v').innerHTML='<iframe src="'+url+'" style="width:100%;height:100%;border:none;"></iframe>';
}})();
</script></body></html>'''
    
    @staticmethod
    def osm_detail(lat, lng, tile_url=None):
        """OSM详细视图"""
        if tile_url is None:
            tile_url = 'https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png'
        
        return f'''<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>#m{{height:100vh;width:100%;}}body{{margin:0;padding:0;}}
.info{{position:absolute;bottom:10px;left:10px;background:rgba(0,0,0,0.7);color:white;padding:8px 12px;border-radius:6px;font-size:13px;z-index:1000;}}</style></head>
<body><div id="m"></div><div class="info">📍 {lat:.6f}, {lng:.6f}</div>
<script>var m=L.map('m',{{center:[{lat},{lng}],zoom:18}});
L.tileLayer('{tile_url}',{{maxZoom:19}}).addTo(m);
L.marker([{lat},{lng}]).addTo(m).bindPopup('目标').openPopup();
L.circle([{lat},{lng}],{{radius:100,color:'#3388ff',fillOpacity:0.1}}).addTo(m);</script></body></html>'''


class ChinaGeoDB:
    """中国地理数据库"""
    CITIES = {
        '北京': (39.9042, 116.4074), '北京市': (39.9042, 116.4074),
        '上海': (31.2304, 121.4737), '上海市': (31.2304, 121.4737),
        '广州': (23.1291, 113.2644), '广州市': (23.1291, 113.2644),
        '深圳': (22.5431, 114.0579), '深圳市': (22.5431, 114.0579),
        '杭州': (30.2741, 120.1551), '杭州市': (30.2741, 120.1551),
        '成都': (30.5728, 104.0668), '成都市': (30.5728, 104.0668),
        '武汉': (30.5928, 114.3055), '武汉市': (30.5928, 114.3055),
        '南京': (32.0603, 118.7969), '南京市': (32.0603, 118.7969),
        '重庆': (29.4316, 106.9123), '重庆市': (29.4316, 106.9123),
        '天津': (39.3434, 117.3616), '天津市': (39.3434, 117.3616),
        '苏州': (31.2990, 120.5853), '苏州市': (31.2990, 120.5853),
        '西安': (34.3416, 108.9398), '西安市': (34.3416, 108.9398),
        '长沙': (28.2282, 112.9388), '长沙市': (28.2282, 112.9388),
        '东莞': (23.0208, 113.7518), '东莞市': (23.0208, 113.7518),
        '佛山': (23.0218, 113.1214), '佛山市': (23.0218, 113.1214),
        '珠海': (22.2707, 113.5767), '珠海市': (22.2707, 113.5767),
        '中山': (22.5159, 113.3926), '中山市': (22.5159, 113.3926),
        '惠州': (23.1107, 114.4168), '惠州市': (23.1107, 114.4168),
        '江门': (22.5787, 113.0819), '江门市': (22.5787, 113.0819),
        '肇庆': (23.0469, 112.4650), '肇庆市': (23.0469, 112.4650),
        '汕头': (23.3535, 116.6820), '汕头市': (23.3535, 116.6820),
        '湛江': (21.2707, 110.3589), '湛江市': (21.2707, 110.3589),
        '茂名': (21.6632, 110.9254), '茂名市': (21.6632, 110.9254),
        '清远': (23.6820, 113.0560), '清远市': (23.6820, 113.0560),
        '揭阳': (23.5497, 116.3727), '揭阳市': (23.5497, 116.3727),
        '韶关': (24.8104, 113.5976), '韶关市': (24.8104, 113.5976),
        '梅州': (24.2886, 116.1225), '梅州市': (24.2886, 116.1225),
        '潮州': (23.6569, 116.6226), '潮州市': (23.6569, 116.6226),
        '河源': (23.7437, 114.7004), '河源市': (23.7437, 114.7004),
        '汕尾': (22.7866, 115.3754), '汕尾市': (22.7866, 115.3754),
        '阳江': (21.8582, 111.9825), '阳江市': (21.8582, 111.9825),
        '云浮': (22.9151, 112.0445), '云浮市': (22.9151, 112.0445),
        '大连': (38.9140, 121.6147), '大连市': (38.9140, 121.6147),
        '青岛': (36.0671, 120.3826), '青岛市': (36.0671, 120.3826),
        '厦门': (24.4798, 118.0894), '厦门市': (24.4798, 118.0894),
        '福州': (26.0745, 119.2965), '福州市': (26.0745, 119.2965),
        '昆明': (25.0389, 102.7183), '昆明市': (25.0389, 102.7183),
        '哈尔滨': (45.8038, 126.5350), '哈尔滨市': (45.8038, 126.5350),
        '长春': (43.8171, 125.3235), '长春市': (43.8171, 125.3235),
        '沈阳': (41.8057, 123.4315), '沈阳市': (41.8057, 123.4315),
        '济南': (36.6512, 117.1201), '济南市': (36.6512, 117.1201),
        '合肥': (31.8206, 117.2272), '合肥市': (31.8206, 117.2272),
        '南昌': (28.6820, 115.8579), '南昌市': (28.6820, 115.8579),
        '郑州': (34.7466, 113.6254), '郑州市': (34.7466, 113.6254),
        '石家庄': (38.0428, 114.5149), '石家庄市': (38.0428, 114.5149),
        '太原': (37.8706, 112.5489), '太原市': (37.8706, 112.5489),
        '南宁': (22.8170, 108.3665), '南宁市': (22.8170, 108.3665),
        '贵阳': (26.6470, 106.6302), '贵阳市': (26.6470, 106.6302),
        '兰州': (36.0611, 103.8343), '兰州市': (36.0611, 103.8343),
        '海口': (20.0440, 110.1999), '海口市': (20.0440, 110.1999),
        '三亚': (18.2528, 109.5120), '三亚市': (18.2528, 109.5120),
        '桂林': (25.2744, 110.2900), '桂林市': (25.2744, 110.2900),
        '拉萨': (29.6500, 91.1000), '拉萨市': (29.6500, 91.1000),
        '乌鲁木齐': (43.8256, 87.6168), '乌鲁木齐市': (43.8256, 87.6168),
        '银川': (38.4872, 106.2309), '银川市': (38.4872, 106.2309),
        '西宁': (36.6171, 101.7782), '西宁市': (36.6171, 101.7782),
        '呼和浩特': (40.8426, 111.7490), '呼和浩特市': (40.8426, 111.7490),
    }
    
    DISTRICTS = {
        # 广州
        '天河': (23.1247, 113.3612), '天河区': (23.1247, 113.3612),
        '海珠': (23.0834, 113.3172), '海珠区': (23.0834, 113.3172),
        '越秀': (23.1285, 113.2668), '越秀区': (23.1285, 113.2668),
        '荔湾': (23.1259, 113.2440), '荔湾区': (23.1259, 113.2440),
        '白云': (23.1579, 113.2730), '白云区': (23.1579, 113.2730),
        '黄埔': (23.1064, 113.4597), '黄埔区': (23.1064, 113.4597),
        '番禺': (22.9379, 113.3842), '番禺区': (22.9379, 113.3842),
        '花都': (23.4042, 113.2203), '花都区': (23.4042, 113.2203),
        '南沙': (22.8013, 113.5250), '南沙区': (22.8013, 113.5250),
        '增城': (23.2609, 113.8109), '增城区': (23.2609, 113.8109),
        '从化': (23.5484, 113.5865), '从化区': (23.5484, 113.5865),
        '赤岗': (23.0900, 113.3200), '客村': (23.0950, 113.3150),
        '琶洲': (23.0980, 113.3450), '珠江新城': (23.1200, 113.3200),
        '体育西': (23.1300, 113.3200), '体育中心': (23.1350, 113.3250),
        '广州塔': (23.1065, 113.3240), '北京路': (23.1200, 113.2650),
        '上下九': (23.1150, 113.2450), '沙面': (23.1100, 113.2400),
        '大学城': (23.0450, 113.3800), '科学城': (23.1650, 113.4400),
        # 深圳
        '福田': (22.5210, 114.0550), '福田区': (22.5210, 114.0550),
        '罗湖': (22.5482, 114.1315), '罗湖区': (22.5482, 114.1315),
        '南山': (22.5328, 113.9305), '南山区': (22.5328, 113.9305),
        '宝安': (22.5552, 113.8830), '宝安区': (22.5552, 113.8830),
        '龙岗': (22.7199, 114.2479), '龙岗区': (22.7199, 114.2479),
        '龙华': (22.6967, 114.0447), '龙华区': (22.6967, 114.0447),
        '坪山': (22.6906, 114.3462), '坪山区': (22.6906, 114.3462),
        '光明': (22.7473, 113.9359), '光明区': (22.7473, 113.9359),
        '盐田': (22.5569, 114.2369), '盐田区': (22.5569, 114.2369),
        '大鹏': (22.5900, 114.4750), '大鹏新区': (22.5900, 114.4750),
        # 北京
        '朝阳': (39.9215, 116.4435), '朝阳区': (39.9215, 116.4435),
        '海淀': (39.9597, 116.2982), '海淀区': (39.9597, 116.2982),
        '东城': (39.9286, 116.4164), '东城区': (39.9286, 116.4164),
        '西城': (39.9123, 116.3659), '西城区': (39.9123, 116.3659),
        '丰台': (39.8585, 116.2870), '丰台区': (39.8585, 116.2870),
        '石景山': (39.9056, 116.2227), '石景山区': (39.9056, 116.2227),
        '通州': (39.9099, 116.6572), '通州区': (39.9099, 116.6572),
        '大兴': (39.7268, 116.3385), '大兴区': (39.7268, 116.3385),
        '昌平': (40.2207, 116.2312), '昌平区': (40.2207, 116.2312),
        '顺义': (40.1302, 116.6544), '顺义区': (40.1302, 116.6544),
        # 上海
        '浦东': (31.2213, 121.5442), '浦东新区': (31.2213, 121.5442),
        '黄浦': (31.2313, 121.4691), '黄浦区': (31.2313, 121.4691),
        '徐汇': (31.1880, 121.4365), '徐汇区': (31.1880, 121.4365),
        '长宁': (31.2204, 121.4246), '长宁区': (31.2204, 121.4246),
        '静安': (31.2274, 121.4472), '静安区': (31.2274, 121.4472),
        '普陀': (31.2496, 121.3970), '普陀区': (31.2496, 121.3970),
        '虹口': (31.2640, 121.5052), '虹口区': (31.2640, 121.5052),
        '杨浦': (31.2596, 121.5261), '杨浦区': (31.2596, 121.5261),
        '闵行': (31.1128, 121.3817), '闵行区': (31.1128, 121.3817),
        '宝山': (31.4053, 121.4897), '宝山区': (31.4053, 121.4897),
        '嘉定': (31.3747, 121.2653), '嘉定区': (31.3747, 121.2653),
        '松江': (31.0322, 121.2277), '松江区': (31.0322, 121.2277),
        '青浦': (31.1498, 121.1242), '青浦区': (31.1498, 121.1242),
        '奉贤': (30.9184, 121.4742), '奉贤区': (30.9184, 121.4742),
        '金山': (30.7419, 121.3424), '金山区': (30.7419, 121.3424),
    }
    
    @classmethod
    def geocode(cls, addr: str) -> Optional[Dict]:
        for c, co in sorted(cls.CITIES.items(), key=lambda x: -len(x[0])):
            if c in addr:
                for d, dc in sorted(cls.DISTRICTS.items(), key=lambda x: -len(x[0])):
                    if d in addr:
                        return {'lat': dc[0], 'lng': dc[1], 'name': f"{addr} ({c}{d})"}
                return {'lat': co[0], 'lng': co[1], 'name': f"{addr} ({c})"}
        for d, dc in sorted(cls.DISTRICTS.items(), key=lambda x: -len(x[0])):
            if d in addr:
                return {'lat': dc[0], 'lng': dc[1], 'name': f"{addr} ({d})"}
        return None


class NetworkTester(QThread):
    """网络测试"""
    result = Signal(str, str)
    progress = Signal(int)
    
    def run(self):
        if not HAS_REQUESTS:
            self.result.emit("❌ pip install requests", "#EF5350")
            return
        
        self._sec("端口测试")
        self._ports()
        
        self._sec("DNS解析")
        self._dns()
        
        self._sec("国内瓦片测试(直连)")
        self._test_tiles('domestic')
        
        self._sec("国外瓦片测试(代理)")
        self._test_tiles('international')
        
        self._sec("街景API")
        self._apis()
        
        self._sec("结果")
        self._sum()
        self.progress.emit(100)
    
    def _sec(self, t):
        self.result.emit(f"\n{'─'*40}", "#666")
        self.result.emit(f" {t}", "#4FC3F7")
        self.result.emit(f"{'─'*40}", "#666")
    
    def _emit(self, m, c="#d4d4d4"):
        self.result.emit(m, c)
    
    def _ports(self):
        tests = [
            ("代理端口", proxy.host, proxy.port),
            ("百度", "www.baidu.com", 443),
            ("高德", "webrd01.is.autonavi.com", 443),
            ("天地图", "t0.tianditu.gov.cn", 443),
            ("腾讯地图", "rt0.map.gtimg.com", 443),
        ]
        for n, h, p in tests:
            try:
                s = socket.socket(); s.settimeout(3)
                r = s.connect_ex((h, p)); s.close()
                self._emit(f"{'✅' if r==0 else '❌'} {n}: {'可达' if r==0 else '不可达'}", 
                          "#66BB6A" if r==0 else "#EF5350")
            except Exception as e:
                self._emit(f"❌ {n}: {e}", "#EF5350")
    
    def _dns(self):
        domains = [
            "webrd01.is.autonavi.com",
            "t0.tianditu.gov.cn",
            "rt0.map.gtimg.com",
            "a.basemaps.cartocdn.com",
            "server.arcgisonline.com",
            "tile.openstreetmap.org",
        ]
        for d in domains:
            try:
                ip = socket.gethostbyname(d)
                self._emit(f"✅ {d} → {ip}", "#66BB6A")
            except:
                self._emit(f"❌ {d}", "#EF5350")
    
    def _test_url(self, n, u, use_proxy=False):
        try:
            px = proxy.get_proxies() if use_proxy else None
            r = requests.get(u, proxies=px, timeout=10,
                           headers={'User-Agent':'Mozilla/5.0'}, verify=False)
            s = len(r.content)
            self._emit(f"✅ {n}: {r.status_code}, {s}B ({r.elapsed.total_seconds():.1f}s)", "#66BB6A")
            return True
        except Exception as e:
            self._emit(f"❌ {n}: {str(e)[:50]}", "#EF5350")
            return False
    
    def _test_tiles(self, region):
        if region == 'domestic':
            tiles = [
                ("高德地图", "https://webrd01.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x=13472&y=7226&z=15", False),
                ("高德卫星", "https://webst01.is.autonavi.com/appmaptile?style=6&x=13472&y=7226&z=15", False),
                ("天地图", "https://t0.tianditu.gov.cn/vec_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=vec&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILEMATRIX=15&TILEROW=7226&TILECOL=13472&tk=", False),
                ("腾讯地图", "https://rt0.map.gtimg.com/tile?z=15&x=13472&y=7226&type=vector&styleid=0", False),
            ]
        else:
            tiles = [
                ("CartoDB", "https://a.basemaps.cartocdn.com/light_all/15/13472/7226.png", True),
                ("ESRI卫星", "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/15/7226/13472", True),
                ("OSM", "https://tile.openstreetmap.org/15/13472/7226.png", True),
                ("Wikimedia", "https://maps.wikimedia.org/osm-intl/15/13472/7226.png", True),
            ]
        
        for n, u, p in tiles:
            self._test_url(n, u, p)
    
    def _apis(self):
        apis = [
            ("Mapillary API", "https://graph.mapillary.com/images?access_token=MLY|44415055e28e08c1f1d01dfcd9a4e2bb&fields=id&limit=1", True),
            ("Mapillary主页", "https://www.mapillary.com", True),
        ]
        for n, u, p in apis:
            self._test_url(n, u, p)
    
    def _sum(self):
        self._emit(f"\n代理: {proxy.host}:{proxy.port} ({'启用' if proxy.enabled else '禁用'})", "#FFE082")
        self._emit("国内地图: 高德/天地图/腾讯 (直连)", "#66BB6A")
        self._emit("国外地图: CartoDB/ESRI (代理)", "#66BB6A")
        self._emit("街景: Mapillary (代理) / 国内无免费API", "#FFB74D")


class Database:
    def __init__(self, p="app_data.db"):
        self.c = sqlite3.connect(p, check_same_thread=False)
        self.c.execute("PRAGMA journal_mode=WAL")
        self.c.execute("CREATE TABLE IF NOT EXISTS h(id INTEGER PRIMARY KEY AUTOINCREMENT, a TEXT, lat REAL, lng REAL, t TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        self.c.execute("CREATE TABLE IF NOT EXISTS s(k TEXT PRIMARY KEY, v TEXT)")
        self.c.commit()
    def add(self, a, lat, lng):
        try: self.c.execute('INSERT INTO h(a,lat,lng) VALUES(?,?,?)',(a,lat,lng)); self.c.commit()
        except: pass
    def get(self, k, d=''):
        try: r=self.c.execute('SELECT v FROM s WHERE k=?',(k,)).fetchone(); return r[0] if r else d
        except: return d
    def set(self, k, v):
        try: self.c.execute('INSERT OR REPLACE INTO s(k,v) VALUES(?,?)',(k,v)); self.c.commit()
        except: pass
    def close(self):
        try: self.c.close()
        except: pass


class MapView(QWebEngineView):
    def __init__(self, p=None):
        super().__init__(p)
        self.loc = None
        self.style = 'cartodb_light'
        self.setMinimumSize(400, 300)
    
    def load(self):
        tiles = {}
        all_tiles = MapTileProviders.get_all()
        for k, v in all_tiles.items():
            sub_js = ''
            if v.get('subdomains'):
                subs = ','.join([f"'{s}'" for s in v['subdomains']])
                sub_js = f"subdomains: [{subs}],"
            tiles[k] = {
                'name': v['name'],
                'url': v['url'],
                'attr': v['attribution'],
                'maxZoom': v['max_zoom'],
                'sub_js': sub_js,
                'region': v['region']
            }
        
        html = f'''<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>#m{{height:100vh;width:100%;}}body{{margin:0;padding:0;}}
.info{{position:absolute;bottom:10px;right:10px;background:rgba(0,0,0,0.7);color:white;padding:6px 10px;border-radius:4px;font-size:12px;z-index:1000;}}</style></head>
<body><div id="m"></div><div class="info" id="mi"></div><script>
var map,mk,cl;var ts={json.dumps(tiles)};
function i(){{map=L.map('m',{{center:[39.9,116.4],zoom:13}});sL('{self.style}');L.control.scale({{imperial:false,position:'bottomleft'}}).addTo(map);
map.on('moveend',function(){{var c=map.getCenter();document.getElementById('mi').innerHTML='📍 '+c.lat.toFixed(5)+', '+c.lng.toFixed(5)+' | 🔍 '+map.getZoom();}});}}
function sL(k){{if(cl)map.removeLayer(cl);var c=ts[k];if(c)cl=L.tileLayer(c.url,{{maxZoom:c.maxZoom,attribution:c.attr,{tiles.get(self.style,{}).get('sub_js','')}}}).addTo(map);}}
function sP(lat,lng,z){{if(map){{map.setView([lat,lng],z||16);if(mk)map.removeLayer(mk);mk=L.marker([lat,lng]).addTo(map).bindPopup('目标').openPopup();}}}}
document.addEventListener('DOMContentLoaded',i);
</script></body></html>'''
        self.setHtml(html)
    
    def set_style(self, k):
        self.style = k
        all_tiles = MapTileProviders.get_all()
        config = all_tiles.get(k, {})
        sub_js = ''
        if config.get('subdomains'):
            subs = ','.join([f"'{s}'" for s in config['subdomains']])
            sub_js = f"subdomains: [{subs}],"
        try:
            self.page().runJavaScript(f"if(typeof sL==='function')sL('{k}');")
        except: pass
    
    def show_loc(self, lat, lng, z=16):
        self.loc = (lat, lng)
        try:
            self.page().runJavaScript(f"if(typeof sP==='function')sP({lat},{lng},{z});")
        except: pass


class StreetView(QWebEngineView):
    def __init__(self, p=None):
        super().__init__(p)
        self.setMinimumSize(400, 300)
        self.setHtml('''<!DOCTYPE html><html><head><meta charset="utf-8"><style>
body{display:flex;justify-content:center;align-items:center;height:100vh;margin:0;background:linear-gradient(135deg,#667eea,#764ba2);font-family:Arial;color:white;}
.w{text-align:center;padding:40px;background:rgba(255,255,255,0.1);border-radius:20px;}
h2{margin-bottom:15px;}p{margin:8px 0;font-size:14px;}
.fl{color:#90EE90;}a{color:#FFD54F;}</style></head>
<body><div class="w"><h2>🌏 街景视图</h2>
<p class="fl">🆓 Mapillary (国外)</p><p>🗺️ 详细地图视图</p>
<p>搜索地址后查看</p></div></body></html>''')
    
    def show_mly(self, lat, lng): self.setHtml(StreetViewProviders.mapillary(lat, lng))
    def show_detail(self, lat, lng, tile_key='cartodb_light'):
        all_tiles = MapTileProviders.get_all()
        tile_url = all_tiles.get(tile_key, {}).get('url', 'https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png')
        self.setHtml(StreetViewProviders.osm_detail(lat, lng, tile_url))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = Database()
        self.clat = self.clng = None
        self.setWindowTitle("地图街景查看器 - 国内外免费服务")
        self.setMinimumSize(1300, 850)
        if Path("icon.ico").exists(): self.setWindowIcon(QIcon("icon.ico"))
        self._setup_proxy()
        self._ui()
        self._load()
        self.statusBar().showMessage("就绪 | 国内:高德/天地图/腾讯 | 国外:CartoDB/ESRI | 街景:Mapillary", 3000)
    
    def _setup_proxy(self):
        if proxy.enabled:
            qp = QNetworkProxy()
            qp.setType(QNetworkProxy.HttpProxy)
            qp.setHostName(proxy.host)
            qp.setPort(proxy.port)
            QNetworkProxy.setApplicationProxy(qp)
    
    def _ui(self):
        c = QWidget()
        self.setCentralWidget(c)
        lo = QVBoxLayout(c)
        lo.setContentsMargins(5,5,5,5)
        lo.setSpacing(5)
        
        sw = QWidget()
        sl = QHBoxLayout(sw)
        sl.setContentsMargins(0,0,0,0)
        sl.addWidget(QLabel("地址:"))
        self.addr = QLineEdit()
        self.addr.setPlaceholderText("输入地址，如：广州海珠区赤岗一街")
        self.addr.returnPressed.connect(self.search)
        sl.addWidget(self.addr, 2)
        self.sbtn = QPushButton("🔍 搜索")
        self.sbtn.clicked.connect(self.search)
        sl.addWidget(self.sbtn)
        lo.addWidget(sw)
        
        sp = QSplitter(Qt.Horizontal)
        lp = QWidget()
        ll = QHBoxLayout(lp)
        ll.setContentsMargins(0,0,0,0)
        
        self.mv = MapView()
        self.mv.load()
        ll.addWidget(self.mv, 1)
        
        cp = QWidget()
        cp.setMaximumWidth(250)
        cl = QVBoxLayout(cp)
        
        # 国内地图
        cl.addWidget(QLabel("🇨🇳 国内地图(直连):"))
        cl.addWidget(QLabel("  无需代理，国内直连"))
        self.dom_cb = QComboBox()
        for k, v in MapTileProviders.DOMESTIC_FREE.items():
            self.dom_cb.addItem(v['name'], k)
        self.dom_cb.currentIndexChanged.connect(lambda: self._switch_style(self.dom_cb.currentData()))
        cl.addWidget(self.dom_cb)
        
        # 国外地图
        cl.addWidget(QLabel("🌍 国外地图(代理):"))
        cl.addWidget(QLabel("  需要代理访问"))
        self.intl_cb = QComboBox()
        for k, v in MapTileProviders.INTERNATIONAL_FREE.items():
            self.intl_cb.addItem(v['name'], k)
        self.intl_cb.currentIndexChanged.connect(lambda: self._switch_style(self.intl_cb.currentData()))
        cl.addWidget(self.intl_cb)
        
        cl.addWidget(QLabel("─" * 20))
        
        cl.addWidget(QLabel("街景视图:"))
        self.svc = QComboBox()
        self.svc.addItem("Mapillary (国外)", "mly")
        self.svc.addItem("详细地图 (当前瓦片)", "detail")
        self.svc.currentIndexChanged.connect(self._sv)
        cl.addWidget(self.svc)
        
        cl.addWidget(QLabel("位置:"))
        self.clbl = QLabel("未定位")
        self.clbl.setWordWrap(True)
        cl.addWidget(self.clbl)
        
        cl.addWidget(QPushButton("📷 Mapillary", clicked=lambda: self._sw("mly")))
        cl.addWidget(QPushButton("🗺️ 详细地图", clicked=lambda: self._sw("detail")))
        cl.addWidget(QPushButton("🔄 刷新", clicked=self._sv))
        
        cl.addStretch()
        ll.addWidget(cp)
        sp.addWidget(lp)
        
        self.sv = StreetView()
        sp.addWidget(self.sv)
        sp.setSizes([750, 550])
        lo.addWidget(sp, 1)
        
        self.setStatusBar(QStatusBar())
        
        mb = self.menuBar()
        tm = mb.addMenu("工具")
        tm.addAction("🔍 网络诊断").triggered.connect(self._diag)
        tm.addSeparator()
        tm.addAction("代理设置").triggered.connect(self._set)
        mb.addAction("关于").triggered.connect(self._about)
    
    def _switch_style(self, style_key):
        """切换地图样式，同步两个下拉框"""
        all_tiles = MapTileProviders.get_all()
        config = all_tiles.get(style_key, {})
        region = config.get('region', 'international')
        
        # 阻止信号避免循环
        self.dom_cb.blockSignals(True)
        self.intl_cb.blockSignals(True)
        
        if region == 'domestic':
            idx = self.dom_cb.findData(style_key)
            if idx >= 0: self.dom_cb.setCurrentIndex(idx)
            self.intl_cb.setCurrentIndex(-1)
        else:
            idx = self.intl_cb.findData(style_key)
            if idx >= 0: self.intl_cb.setCurrentIndex(idx)
            self.dom_cb.setCurrentIndex(-1)
        
        self.dom_cb.blockSignals(False)
        self.intl_cb.blockSignals(False)
        
        self.mv.set_style(style_key)
    
    def search(self):
        a = self.addr.text().strip()
        if not a: return self.statusBar().showMessage("请输入地址", 3000)
        r = ChinaGeoDB.geocode(a)
        if r:
            self.clat, self.clng = r['lat'], r['lng']
            self.mv.show_loc(self.clat, self.clng)
            self.clbl.setText(f"纬度: {self.clat:.6f}\n经度: {self.clng:.6f}")
            self._sv()
            self.statusBar().showMessage(f"✅ {r['name']}", 5000)
        else:
            self.statusBar().showMessage("❌ 无法解析地址", 5000)
    
    def _sv(self):
        if not self.clat: return
        p = self.svc.currentData()
        if p == 'mly':
            self.sv.show_mly(self.clat, self.clng)
        else:
            # 使用当前地图样式作为详细视图的瓦片
            current_style = self.mv.style
            self.sv.show_detail(self.clat, self.clng, current_style)
    
    def _sw(self, p):
        for i in range(self.svc.count()):
            if self.svc.itemData(i) == p: self.svc.setCurrentIndex(i); break
        self._sv()
    
    def _diag(self):
        if not HAS_REQUESTS:
            QMessageBox.warning(self, "缺少依赖", "请安装: pip install requests")
            return
        
        dlg = QDialog(self)
        dlg.setWindowTitle("网络诊断")
        dlg.setMinimumSize(650, 550)
        lo = QVBoxLayout(dlg)
        
        info = QGroupBox("信息")
        il = QVBoxLayout(info)
        il.addWidget(QLabel(f"代理: {proxy.host}:{proxy.port} ({'✅' if proxy.enabled else '❌'})"))
        il.addWidget(QLabel("国内服务: 直连"))
        il.addWidget(QLabel("国外服务: 通过代理"))
        lo.addWidget(info)
        
        self.dtext = QTextEdit()
        self.dtext.setReadOnly(True)
        self.dtext.setStyleSheet("background:#1e1e1e;color:#d4d4d4;font-family:Consolas,monospace;font-size:12px;")
        lo.addWidget(self.dtext)
        
        dpb = QProgressBar()
        lo.addWidget(dpb)
        
        bl = QHBoxLayout()
        b1 = QPushButton("开始诊断")
        b2 = QPushButton("关闭")
        bl.addWidget(b1)
        bl.addWidget(b2)
        lo.addLayout(bl)
        
        tester = None
        def start():
            nonlocal tester
            b1.setEnabled(False)
            self.dtext.clear()
            tester = NetworkTester()
            tester.result.connect(lambda m,c: self.dtext.append(f'<span style="color:{c}">{m}</span>'))
            tester.progress.connect(dpb.setValue)
            tester.finished.connect(lambda: b1.setEnabled(True))
            tester.start()
        
        b1.clicked.connect(start)
        b2.clicked.connect(dlg.accept)
        dlg.finished.connect(lambda: tester.stop() if tester and tester.isRunning() else None)
        dlg.exec()
    
    def _set(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("代理设置")
        lo = QVBoxLayout(dlg)
        g = QGroupBox("HTTP代理 (国外服务)")
        f = QVBoxLayout(g)
        pe = QCheckBox("启用代理"); pe.setChecked(proxy.enabled); f.addWidget(pe)
        h = QHBoxLayout(); h.addWidget(QLabel("地址:")); ph = QLineEdit(proxy.host); h.addWidget(ph); f.addLayout(h)
        p = QHBoxLayout(); p.addWidget(QLabel("端口:")); pp = QSpinBox(); pp.setRange(1,65535); pp.setValue(proxy.port); p.addWidget(pp); f.addLayout(p)
        note = QLabel("⚠️ 修改后需重启")
        note.setStyleSheet("color:#FF9800;"); f.addWidget(note)
        lo.addWidget(g); lo.addStretch()
        bl = QHBoxLayout()
        bl.addWidget(QPushButton("保存", clicked=lambda: self._save_set(dlg, pe, ph, pp)))
        bl.addWidget(QPushButton("取消", clicked=dlg.reject))
        lo.addLayout(bl)
        dlg.exec()
    
    def _save_set(self, dlg, pe, ph, pp):
        proxy.enabled = pe.isChecked()
        proxy.host = ph.text()
        proxy.port = pp.value()
        proxy.save()
        dlg.accept()
        self.statusBar().showMessage("已保存，建议重启", 3000)
    
    def _about(self):
        QMessageBox.about(self, "关于",
            "地图街景查看器\n\n"
            "🇨🇳 国内免费地图(直连):\n"
            "• 高德地图 / 高德卫星图\n"
            "• 天地图 / 天地图卫星图\n"
            "• 腾讯地图\n\n"
            "🌍 国外免费地图(代理):\n"
            "• CartoDB Light/Dark\n"
            "• ESRI 卫星图/街道图\n"
            "• OpenStreetMap / Wikimedia\n\n"
            "📷 街景: Mapillary (国外,代理)\n\n"
            "代理: 127.0.0.1:20808")
    
    def _load(self):
        try:
            g = QSettings("MapLocator", "MainWindow").value("geometry")
            if g: self.restoreGeometry(g)
        except: pass
    
    def closeEvent(self, e):
        try: QSettings("MapLocator", "MainWindow").setValue("geometry", self.saveGeometry())
        except: pass
        self.db.close()
        e.accept()


def main():
    try:
        QApplication.setAttribute(Qt.AA_Use96Dpi)
        app = QApplication(sys.argv)
        app.setStyle('Fusion')
        
        if not HAS_REQUESTS:
            QMessageBox.warning(None, "提示", "建议安装: pip install requests")
        
        MainWindow().show()
        sys.exit(app.exec())
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()