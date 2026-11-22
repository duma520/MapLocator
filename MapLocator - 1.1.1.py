#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
地图街景查看器 - QtWebEngine代理配置版
修复浏览器内核不使用系统代理的问题
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

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox,
    QStatusBar, QProgressBar, QMessageBox,
    QDialog, QSplitter, QGroupBox, QCheckBox, QSpinBox,
    QTextEdit
)
from PySide6.QtCore import Qt, QThread, Signal, QSettings, QTimer, QMutex, QUrl
from PySide6.QtGui import QIcon
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEngineSettings
from PySide6.QtNetwork import QNetworkProxy, QNetworkProxyFactory

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# 禁用SSL警告
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


class ProxyManager:
    """代理管理器"""
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
        except:
            pass
    
    def save(self):
        s = QSettings("MapLocator", "Proxy")
        s.setValue("enabled", str(self.enabled).lower())
        s.setValue("host", self.host)
        s.setValue("port", self.port)
    
    def get_proxies(self) -> Optional[Dict]:
        if not self.enabled: return None
        url = f"http://{self.host}:{self.port}"
        return {'http': url, 'https': url}


proxy = ProxyManager()


class NetworkTester(QThread):
    """网络测试线程"""
    result = Signal(str, str)
    progress = Signal(int)
    
    def run(self):
        if not HAS_REQUESTS:
            self.result.emit("❌ 需要安装: pip install requests", "#EF5350")
            return
        
        self._section("端口测试")
        self._ports()
        
        self._section("DNS解析")
        self._dns()
        
        self._section("地图瓦片 (通过代理)")
        self._tiles()
        
        self._section("街景API")
        self._apis()
        
        self._section("结果")
        self._summary()
        self.progress.emit(100)
    
    def _section(self, t):
        self.result.emit(f"\n{'='*40}", "#666")
        self.result.emit(f"  {t}", "#4FC3F7")
        self.result.emit(f"{'='*40}", "#666")
    
    def _emit(self, m, c="#d4d4d4"):
        self.result.emit(m, c)
    
    def _ports(self):
        for n, h, p in [("代理", proxy.host, proxy.port),
                          ("百度", "www.baidu.com", 443),
                          ("OSM", "tile.openstreetmap.org", 443),
                          ("Mapillary", "graph.mapillary.com", 443)]:
            try:
                s = socket.socket(); s.settimeout(5)
                r = s.connect_ex((h, p)); s.close()
                self._emit(f"{'✅' if r==0 else '❌'} {n}:{'可达' if r==0 else '不可达'}", 
                          "#66BB6A" if r==0 else "#EF5350")
            except Exception as e:
                self._emit(f"❌ {n}: {e}", "#EF5350")
    
    def _dns(self):
        for d in ["tile.openstreetmap.org", "graph.mapillary.com",
                   "a.basemaps.cartocdn.com", "server.arcgisonline.com"]:
            try:
                ip = socket.gethostbyname(d)
                self._emit(f"✅ {d} → {ip}", "#66BB6A")
            except:
                self._emit(f"❌ {d}", "#EF5350")
    
    def _test(self, n, u, t=15):
        try:
            r = requests.get(u, proxies=proxy.get_proxies(), timeout=t,
                           headers={'User-Agent':'Mozilla/5.0'}, verify=False)
            s = len(r.content)
            self._emit(f"✅ {n}: {r.status_code}, {s}B ({r.elapsed.total_seconds():.1f}s)", "#66BB6A")
            return True
        except requests.Timeout:
            self._emit(f"❌ {n}: 超时", "#EF5350")
        except Exception as e:
            self._emit(f"❌ {n}: {str(e)[:50]}", "#EF5350")
        return False
    
    def _tiles(self):
        # 根据之前的诊断，CartoDB和ESRI可用
        tiles = [
            ("CartoDB", "https://a.basemaps.cartocdn.com/light_all/15/13472/7226.png"),
            ("ESRI卫星", "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/15/7226/13472"),
            ("OSM", "https://tile.openstreetmap.org/15/13472/7226.png"),
            ("OSM HTTP", "http://tile.openstreetmap.org/15/13472/7226.png"),
        ]
        for n, u in tiles:
            self._test(n, u)
    
    def _apis(self):
        apis = [
            ("Mapillary主页", "https://www.mapillary.com"),
            ("Mapillary API", "https://graph.mapillary.com/images?access_token=MLY|44415055e28e08c1f1d01dfcd9a4e2bb&fields=id&limit=1"),
        ]
        for n, u in apis:
            self._test(n, u)
    
    def _summary(self):
        self._emit(f"\n代理: {proxy.host}:{proxy.port} ({'启用' if proxy.enabled else '禁用'})", "#FFE082")
        self._emit("提示: 浏览器内核需要单独配置代理", "#FFB74D")
        self._emit("地图使用: CartoDB Light / ESRI Satellite", "#66BB6A")


class ChinaGeoDB:
    """地理数据库"""
    CITIES = {
        '北京': (39.9042, 116.4074), '上海': (31.2304, 121.4737),
        '广州': (23.1291, 113.2644), '深圳': (22.5431, 114.0579),
        '杭州': (30.2741, 120.1551), '成都': (30.5728, 104.0668),
        '武汉': (30.5928, 114.3055), '南京': (32.0603, 118.7969),
        '重庆': (29.4316, 106.9123), '天津': (39.3434, 117.3616),
        '苏州': (31.2990, 120.5853), '西安': (34.3416, 108.9398),
        '长沙': (28.2282, 112.9388), '东莞': (23.0208, 113.7518),
        '佛山': (23.0218, 113.1214), '珠海': (22.2707, 113.5767),
        '大连': (38.9140, 121.6147), '青岛': (36.0671, 120.3826),
        '厦门': (24.4798, 118.0894), '福州': (26.0745, 119.2965),
        '昆明': (25.0389, 102.7183), '哈尔滨': (45.8038, 126.5350),
        '沈阳': (41.8057, 123.4315), '济南': (36.6512, 117.1201),
        '南宁': (22.8170, 108.3665), '贵阳': (26.6470, 106.6302),
        '海口': (20.0440, 110.1999), '三亚': (18.2528, 109.5120),
    }
    
    DISTRICTS = {
        '天河': (23.1247, 113.3612), '海珠': (23.0834, 113.3172),
        '越秀': (23.1285, 113.2668), '荔湾': (23.1259, 113.2440),
        '白云': (23.1579, 113.2730), '黄埔': (23.1064, 113.4597),
        '番禺': (22.9379, 113.3842), '花都': (23.4042, 113.2203),
        '南沙': (22.8013, 113.5250), '增城': (23.2609, 113.8109),
        '从化': (23.5484, 113.5865), '赤岗': (23.0900, 113.3200),
        '客村': (23.0950, 113.3150), '琶洲': (23.0980, 113.3450),
        '珠江新城': (23.1200, 113.3200),
        '福田': (22.5210, 114.0550), '罗湖': (22.5482, 114.1315),
        '南山': (22.5328, 113.9305), '宝安': (22.5552, 113.8830),
        '龙岗': (22.7199, 114.2479), '龙华': (22.6967, 114.0447),
        '朝阳': (39.9215, 116.4435), '海淀': (39.9597, 116.2982),
        '东城': (39.9286, 116.4164), '西城': (39.9123, 116.3659),
        '浦东': (31.2213, 121.5442), '黄浦': (31.2313, 121.4691),
        '徐汇': (31.1880, 121.4365), '静安': (31.2274, 121.4472),
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


class MapHTML:
    """地图HTML - 使用可用的瓦片源"""
    
    # 根据诊断结果，只保留可用的地图源
    STYLES = {
        'carto_light': ('CartoDB Light', 'https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png', '© CartoDB'),
        'carto_dark': ('CartoDB Dark', 'https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png', '© CartoDB'),
        'esri_satellite': ('ESRI 卫星图', 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', '© Esri'),
        'esri_street': ('ESRI 街道图', 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}', '© Esri'),
        'osm': ('OpenStreetMap', 'https://tile.openstreetmap.org/{z}/{x}/{y}.png', '© OSM'),
    }
    
    @staticmethod
    def tile_test():
        return '''<!DOCTYPE html><html><head><meta charset="utf-8">
<style>body{margin:10px;font-family:Arial;background:#f5f5f5;}
.row{display:flex;flex-wrap:wrap;gap:10px;}.box{text-align:center;margin-bottom:10px;}
.tile{width:128px;height:128px;border:2px solid #ddd;border-radius:4px;background:white;}
.tile img{width:100%;height:100%;object-fit:cover;}
.lb{font-size:11px;margin-top:4px;color:#666;}
.ok{border-color:#4CAF50!important;box-shadow:0 0 8px rgba(76,175,80,0.5);}
.fail{border-color:#f44336!important;}
.info{background:white;padding:10px;border-radius:8px;margin-bottom:10px;font-size:13px;}
</style></head><body>
<h3>🗺️ 瓦片测试 - 广州赤岗</h3>
<div class="info">代理: 127.0.0.1:20808 | 仅测试可用的瓦片源</div>
<div class="row">
<div class="box"><div class="tile"><img src="https://a.basemaps.cartocdn.com/light_all/15/13472/7226.png" 
onload="this.parentElement.classList.add('ok')" 
onerror="this.parentElement.classList.add('fail');this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%22128%22 height=%22128%22><rect fill=%22%23ffebee%22 width=%22128%22 height=%22128%22/><text fill=%22%23c62828%22 x=%2215%22 y=%2264%22 font-size=%2212%22>CartoDB失败</text></svg>';"></div><div class="lb">CartoDB Light</div></div>
<div class="box"><div class="tile"><img src="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/15/7226/13472" 
onload="this.parentElement.classList.add('ok')" 
onerror="this.parentElement.classList.add('fail');this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%22128%22 height=%22128%22><rect fill=%22%23ffebee%22 width=%22128%22 height=%22128%22/><text fill=%22%23c62828%22 x=%2220%22 y=%2264%22 font-size=%2212%22>ESRI失败</text></svg>';"></div><div class="lb">ESRI 卫星图</div></div>
<div class="box"><div class="tile"><img src="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/15/7226/13472" 
onload="this.parentElement.classList.add('ok')" 
onerror="this.parentElement.classList.add('fail');this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%22128%22 height=%22128%22><rect fill=%22%23ffebee%22 width=%22128%22 height=%22128%22/><text fill=%22%23c62828%22 x=%2220%22 y=%2264%22 font-size=%2212%22>ESRI失败</text></svg>';"></div><div class="lb">ESRI 街道图</div></div>
<div class="box"><div class="tile"><img src="https://tile.openstreetmap.org/15/13472/7226.png" 
onload="this.parentElement.classList.add('ok')" 
onerror="this.parentElement.classList.add('fail');this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%22128%22 height=%22128%22><rect fill=%22%23ffebee%22 width=%22128%22 height=%22128%22/><text fill=%22%23c62828%22 x=%2220%22 y=%2264%22 font-size=%2212%22>OSM失败</text></svg>';"></div><div class="lb">OpenStreetMap</div></div>
</div>
<p style="color:#999;font-size:12px;">✅ 绿色=可用 | ❌ 红色=不可用</p>
</body></html>'''
    
    @classmethod
    def generate(cls, style='carto_light'):
        tiles = {}
        for k, v in cls.STYLES.items():
            tiles[k] = {'name': v[0], 'url': v[1], 'attr': v[2]}
        
        return f'''<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>#m{{height:100vh;width:100%;}}body{{margin:0;padding:0;}}</style></head>
<body><div id="m"></div><script>
var map,mk,cl;var ts={json.dumps(tiles)};
function i(){{map=L.map('m',{{center:[39.9,116.4],zoom:13}});sL('{style}');}}
function sL(k){{if(cl)map.removeLayer(cl);var c=ts[k];if(c)cl=L.tileLayer(c.url,{{maxZoom:19,attribution:c.attr}}).addTo(map);}}
function sP(lat,lng,z){{if(map){{map.setView([lat,lng],z||16);if(mk)map.removeLayer(mk);mk=L.marker([lat,lng]).addTo(map).bindPopup('目标').openPopup();}}}}
document.addEventListener('DOMContentLoaded',i);
</script></body></html>'''


class StreetViewHTML:
    """街景HTML"""
    
    @staticmethod
    def mapillary(lat, lng):
        """Mapillary iframe"""
        return f'''<!DOCTYPE html><html><head><meta charset="utf-8">
<style>*{{margin:0;padding:0;}}html,body,#v{{width:100%;height:100%;}}
#v{{display:flex;justify-content:center;align-items:center;background:#f0f0f0;font-family:Arial;}}</style></head>
<body><div id="v"><div style="text-align:center;">
<p>正在加载Mapillary...</p><p style="color:#999;">坐标: {lat:.4f}, {lng:.4f}</p></div></div>
<script>
(function(){{
var t='MLY|44415055e28e08c1f1d01dfcd9a4e2bb';
fetch('https://graph.mapillary.com/images?access_token='+t+'&fields=id&limit=3&closest_to='+{lng}+','+{lat})
.then(r=>r.json()).then(d=>{{
if(d.data&&d.data.length>0)document.getElementById('v').innerHTML='<iframe src=\"https://www.mapillary.com/embed?image_key='+d.data[0].id+'\" style=\"width:100%;height:100%;border:none;\"></iframe>';
else document.getElementById('v').innerHTML='<div style="text-align:center;padding:20px;background:#fff3cd;border-radius:10px;"><h3>此处无街景</h3><p>坐标: {lat:.4f}, {lng:.4f}</p></div>';
}}).catch(e=>{{document.getElementById('v').innerHTML='<div style="text-align:center;padding:20px;background:#fff3cd;border-radius:10px;"><h3>加载失败</h3><p>'+e.message+'</p></div>';}});
}})();</script></body></html>'''
    
    @staticmethod
    def osm_detail(lat, lng):
        """OSM详细视图 - 使用CartoDB瓦片（可用）"""
        return f'''<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>#m{{height:100vh;width:100%;}}body{{margin:0;padding:0;}}
.info{{position:absolute;bottom:10px;left:10px;background:rgba(0,0,0,0.7);color:white;padding:8px 12px;border-radius:6px;font-size:13px;z-index:1000;}}</style></head>
<body><div id="m"></div><div class="info">📍 {lat:.6f}, {lng:.6f}</div>
<script>var m=L.map('m',{{center:[{lat},{lng}],zoom:18}});
// 使用可用的CartoDB瓦片
L.tileLayer('https://a.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}.png',{{maxZoom:19,attribution:'© CartoDB'}}).addTo(m);
L.marker([{lat},{lng}]).addTo(m).bindPopup('目标位置').openPopup();
L.circle([{lat},{lng}],{{radius:100,color:'#3388ff',fillOpacity:0.1}}).addTo(m);</script></body></html>'''


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
        self.style = 'carto_light'  # 默认使用可用的CartoDB
        self.setMinimumSize(400, 300)
    def load(self): self.setHtml(MapHTML.generate(self.style))
    def set_style(self, k):
        self.style = k
        try: self.page().runJavaScript(f"if(typeof sL==='function')sL('{k}');")
        except: pass
    def show_loc(self, lat, lng, z=16):
        self.loc = (lat, lng)
        try: self.page().runJavaScript(f"if(typeof sP==='function')sP({lat},{lng},{z});")
        except: pass
    def show_tiles(self): self.setHtml(MapHTML.tile_test())


class StreetView(QWebEngineView):
    def __init__(self, p=None):
        super().__init__(p)
        self.setMinimumSize(400, 300)
        self.setHtml('''<!DOCTYPE html><html><head><meta charset="utf-8"><style>
body{display:flex;justify-content:center;align-items:center;height:100vh;margin:0;background:linear-gradient(135deg,#667eea,#764ba2);font-family:Arial;color:white;}
.w{text-align:center;padding:40px;background:rgba(255,255,255,0.1);border-radius:20px;}
h2{margin-bottom:15px;}p{margin:8px 0;font-size:14px;}</style></head>
<body><div class="w"><h2>🌏 街景视图</h2><p>搜索地址查看街景</p></div></body></html>''')
    def show_mly(self, lat, lng): self.setHtml(StreetViewHTML.mapillary(lat, lng))
    def show_osm(self, lat, lng): self.setHtml(StreetViewHTML.osm_detail(lat, lng))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = Database()
        self.clat = self.clng = None
        self.setWindowTitle("地图街景查看器")
        self.setMinimumSize(1200, 800)
        if Path("icon.ico").exists(): self.setWindowIcon(QIcon("icon.ico"))
        
        # 配置QtWebEngine代理
        self._setup_proxy()
        
        self._ui()
        self._load()
        self.statusBar().showMessage("就绪 | 默认CartoDB+ESRI | 工具→网络诊断/瓦片测试", 3000)
    
    def _setup_proxy(self):
        """为QtWebEngine配置代理"""
        if proxy.enabled:
            # 设置应用程序级别的代理
            q_proxy = QNetworkProxy()
            q_proxy.setType(QNetworkProxy.HttpProxy)
            q_proxy.setHostName(proxy.host)
            q_proxy.setPort(proxy.port)
            QNetworkProxy.setApplicationProxy(q_proxy)
            
            logger.info(f"QtWebEngine代理已设置: {proxy.host}:{proxy.port}")
    
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
        cp.setMaximumWidth(200)
        cl = QVBoxLayout(cp)
        cl.addWidget(QLabel("地图样式:"))
        self.scb = QComboBox()
        for k, v in MapHTML.STYLES.items(): self.scb.addItem(v[0], k)
        self.scb.currentIndexChanged.connect(lambda: self.mv.set_style(self.scb.currentData()))
        cl.addWidget(self.scb)
        cl.addWidget(QLabel("街景:"))
        self.svc = QComboBox()
        self.svc.addItem("Mapillary", "mly")
        self.svc.addItem("OSM详细", "osm")
        self.svc.currentIndexChanged.connect(self._sv)
        cl.addWidget(self.svc)
        cl.addWidget(QLabel("位置:"))
        self.clbl = QLabel("未定位")
        self.clbl.setWordWrap(True)
        cl.addWidget(self.clbl)
        cl.addWidget(QPushButton("📷 Mapillary", clicked=lambda: self._sw("mly")))
        cl.addWidget(QPushButton("🗺️ OSM详细", clicked=lambda: self._sw("osm")))
        cl.addWidget(QPushButton("🔄 刷新", clicked=self._sv))
        cl.addStretch()
        ll.addWidget(cp)
        sp.addWidget(lp)
        
        self.sv = StreetView()
        sp.addWidget(self.sv)
        sp.setSizes([700, 500])
        lo.addWidget(sp, 1)
        
        self.setStatusBar(QStatusBar())
        
        mb = self.menuBar()
        tm = mb.addMenu("工具")
        tm.addAction("🔍 网络诊断").triggered.connect(self._diag)
        tm.addAction("🗺️ 瓦片测试").triggered.connect(lambda: self.mv.show_tiles())
        tm.addSeparator()
        tm.addAction("代理设置").triggered.connect(self._set)
        mb.addAction("关于").triggered.connect(lambda: QMessageBox.about(self, "关于", 
            "地图街景查看器\n\n"
            "可用瓦片: CartoDB Light/Dark, ESRI卫星/街道\n"
            "街景: Mapillary (需代理)\n\n"
            "代理: 127.0.0.1:20808\n"
            "工具→网络诊断 测试连接"))
    
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
        if p == 'mly': self.sv.show_mly(self.clat, self.clng)
        else: self.sv.show_osm(self.clat, self.clng)
    
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
        dlg.setMinimumSize(600, 500)
        lo = QVBoxLayout(dlg)
        
        info = QGroupBox("信息")
        il = QVBoxLayout(info)
        il.addWidget(QLabel(f"代理: {proxy.host}:{proxy.port} ({'启用' if proxy.enabled else '禁用'})"))
        il.addWidget(QLabel(f"QtWebEngine代理: {'已配置' if proxy.enabled else '未配置'}"))
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
        g = QGroupBox("HTTP代理")
        f = QVBoxLayout(g)
        pe = QCheckBox("启用代理"); pe.setChecked(proxy.enabled); f.addWidget(pe)
        h = QHBoxLayout(); h.addWidget(QLabel("地址:")); ph = QLineEdit(proxy.host); h.addWidget(ph); f.addLayout(h)
        p = QHBoxLayout(); p.addWidget(QLabel("端口:")); pp = QSpinBox(); pp.setRange(1,65535); pp.setValue(proxy.port); p.addWidget(pp); f.addLayout(p)
        note = QLabel("⚠️ 修改后需重启程序生效")
        note.setStyleSheet("color:#FF9800;")
        f.addWidget(note)
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
        # 重新配置代理
        self._setup_proxy()
        self.statusBar().showMessage("已保存，建议重启程序", 3000)
    
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
        
        # 检查依赖
        if not HAS_REQUESTS:
            QMessageBox.warning(None, "缺少依赖", 
                "请安装requests库:\npip install requests\n\n"
                "或继续使用（仅限离线功能）")
        
        MainWindow().show()
        sys.exit(app.exec())
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()