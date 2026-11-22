#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
地址定位与街景查看系统
功能：输入地址，显示地图位置和街景，支持国内外多种地图服务
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
from pypinyin import pinyin, lazy_pinyin
import urllib.parse
import logging

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QTabWidget,
    QStatusBar, QProgressBar, QMessageBox, QFileDialog,
    QDialog, QTableWidget, QTableWidgetItem, QHeaderView,
    QSplitter, QGroupBox, QCheckBox, QSpinBox, QTextEdit,
    QDateTimeEdit, QDialogButtonBox, QRadioButton, QButtonGroup,
    QSystemTrayIcon, QMenu, QStyle, QFrame
)
from PySide6.QtCore import (
    Qt, QThread, Signal, QUrl, QSettings, QTimer,
    QDateTime, QMutex, QWaitCondition, QCoreApplication
)
from PySide6.QtGui import QIcon, QAction, QPainter, QColor
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


class UniqueNamingMixin:
    """确保类名和方法名唯一性的混入类"""
    _class_registry = {}
    _method_registry = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        class_name = cls.__name__
        if class_name in UniqueNamingMixin._class_registry:
            raise NameError(f"类名冲突: {class_name} 已存在")
        UniqueNamingMixin._class_registry[class_name] = cls


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
                search_count INTEGER DEFAULT 1
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

    def get_connection(self):
        """获取数据库连接（线程安全）"""
        self.mutex.lock()
        if not self.connection:
            self._initialize_database()
        self.mutex.unlock()
        return self.connection

    def search_all_data(self, search_text: str) -> List[Dict]:
        """搜索全部数据（支持中英文、拼音首字母）"""
        cursor = self.get_connection().cursor()

        # 获取拼音首字母
        pinyin_initial = ''.join([p[0][0] if p else '' for p in pinyin(search_text, style=Style.TONE3)])
        full_pinyin = ''.join(lazy_pinyin(search_text))

        query = '''
            SELECT id, address, latitude, longitude, location_type, search_time
            FROM location_history 
            WHERE address LIKE ? 
               OR address LIKE ? 
               OR address LIKE ?
            ORDER BY search_time DESC
            LIMIT 100
        '''

        search_patterns = (
            f'%{search_text}%',
            f'%{pinyin_initial}%',
            f'%{full_pinyin}%'
        )

        cursor.execute(query, search_patterns)
        columns = [desc[0] for desc in cursor.description]
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]
        return results

    def add_location_record(self, address: str, lat: float, lon: float, loc_type: str):
        """添加位置记录"""
        cursor = self.get_connection().cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO location_history 
            (address, latitude, longitude, location_type, search_time, search_count)
            VALUES (
                ?, ?, ?, ?, CURRENT_TIMESTAMP,
                COALESCE((SELECT search_count + 1 FROM location_history WHERE address = ?), 1)
            )
        ''', (address, lat, lon, loc_type, address))
        self.get_connection().commit()

    def get_backup_list(self, backup_type: str = None,
                        start_time: str = None,
                        end_time: str = None) -> List[Dict]:
        """获取备份列表"""
        cursor = self.get_connection().cursor()
        query = '''
            SELECT id, backup_time, backup_type, file_name, file_size, 
                   db_version, date_range_start, date_range_end, record_count
            FROM backup_records WHERE 1=1
        '''
        params = []

        if backup_type and backup_type != 'all':
            query += ' AND backup_type = ?'
            params.append(backup_type)

        if start_time:
            query += ' AND backup_time >= ?'
            params.append(start_time)

        if end_time:
            query += ' AND backup_time <= ?'
            params.append(end_time)

        query += ' ORDER BY backup_time DESC'

        cursor.execute(query, params)
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def create_backup(self, backup_type: str = 'auto') -> str:
        """创建数据库备份（WAL模式）"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_file = self.backup_dir / f"backup_{timestamp}.db"
        temp_backup = self.backup_dir / f"temp_{timestamp}.db"

        try:
            # WAL模式备份 - 先checkpoint
            self.get_connection().execute("PRAGMA wal_checkpoint(FULL)")

            # 创建备份
            source = sqlite3.connect(self.db_path)
            dest = sqlite3.connect(str(temp_backup))
            source.backup(dest)
            dest.close()
            source.close()

            # 压缩备份
            zip_file = self.backup_dir / f"backup_{timestamp}.zip"
            with zipfile.ZipFile(zip_file, 'w', zipfile.ZIP_DEFLATED) as zf:
                zf.write(temp_backup, f"backup_{timestamp}.db")
                # 添加版本信息
                version_info = self._get_database_info()
                zf.writestr("version_info.json", json.dumps(version_info))

            # 删除临时文件
            if temp_backup.exists():
                temp_backup.unlink()

            # 记录备份信息
            file_size = zip_file.stat().st_size
            db_info = self._get_database_info()
            cursor = self.get_connection().cursor()
            cursor.execute('''
                INSERT INTO backup_records 
                (backup_type, file_name, file_size, db_version, 
                 date_range_start, date_range_end, record_count)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                backup_type,
                zip_file.name,
                file_size,
                db_info.get('version', '1.0'),
                db_info.get('earliest_record'),
                db_info.get('latest_record'),
                db_info.get('total_records', 0)
            ))
            self.get_connection().commit()

            # 清理旧备份
            self._cleanup_old_backups()

            return str(zip_file)

        except Exception as e:
            logger.error(f"备份失败: {e}")
            if temp_backup.exists():
                temp_backup.unlink()
            raise

    def _get_database_info(self) -> Dict:
        """获取数据库信息"""
        cursor = self.get_connection().cursor()
        cursor.execute("SELECT COUNT(*) FROM location_history")
        total_records = cursor.fetchone()[0]

        cursor.execute("SELECT MIN(search_time), MAX(search_time) FROM location_history")
        date_range = cursor.fetchone()

        return {
            'version': '1.0',
            'total_records': total_records,
            'earliest_record': date_range[0] if date_range[0] else None,
            'latest_record': date_range[1] if date_range[1] else None,
            'backup_time': datetime.now().isoformat()
        }

    def _cleanup_old_backups(self):
        """清理旧备份文件"""
        cursor = self.get_connection().cursor()
        cursor.execute('''
            SELECT id, file_name FROM backup_records 
            ORDER BY backup_time DESC LIMIT -1 OFFSET ?
        ''', (self.max_backups,))
        old_backups = cursor.fetchall()

        for backup_id, file_name in old_backups:
            file_path = self.backup_dir / file_name
            if file_path.exists():
                file_path.unlink()
            cursor.execute('DELETE FROM backup_records WHERE id = ?', (backup_id,))

        self.get_connection().commit()

    def restore_backup(self, backup_id: int) -> bool:
        """恢复数据库备份（恢复前自动备份）"""
        cursor = self.get_connection().cursor()
        cursor.execute('SELECT file_name FROM backup_records WHERE id = ?', (backup_id,))
        result = cursor.fetchone()

        if not result:
            raise ValueError(f"未找到备份记录: {backup_id}")

        file_name = result[0]
        backup_path = self.backup_dir / file_name

        if not backup_path.exists():
            raise FileNotFoundError(f"备份文件不存在: {backup_path}")

        # 恢复前备份当前数据库
        self.create_backup('rollback')

        try:
            # 关闭当前连接
            if self.connection:
                self.connection.close()

            # 从zip解压
            temp_dir = self.backup_dir / "temp_restore"
            temp_dir.mkdir(exist_ok=True)

            with zipfile.ZipFile(backup_path, 'r') as zf:
                zf.extractall(temp_dir)

            # 找到数据库文件
            db_files = list(temp_dir.glob("*.db"))
            if not db_files:
                raise ValueError("备份文件中未找到数据库文件")

            # 替换当前数据库
            shutil.copy2(db_files[0], self.db_path)

            # 清理临时文件
            shutil.rmtree(temp_dir)

            # 重新初始化连接
            self._initialize_database()

            return True

        except Exception as e:
            logger.error(f"恢复失败: {e}")
            # 尝试重新连接
            self._initialize_database()
            raise

    def rollback_backup(self, backup_id: int) -> bool:
        """回滚到指定备份"""
        return self.restore_backup(backup_id)

    def save_api_settings(self, service_name: str, api_data: Dict):
        """保存API设置"""
        cursor = self.get_connection().cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO api_settings 
            (service_name, api_key, api_secret, additional_params, last_updated)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (
            service_name,
            api_data.get('api_key'),
            api_data.get('api_secret'),
            json.dumps(api_data.get('additional_params', {}))
        ))
        self.get_connection().commit()

    def get_api_settings(self, service_name: str) -> Optional[Dict]:
        """获取API设置"""
        cursor = self.get_connection().cursor()
        cursor.execute('''
            SELECT api_key, api_secret, additional_params 
            FROM api_settings WHERE service_name = ?
        ''', (service_name,))
        result = cursor.fetchone()

        if result:
            return {
                'api_key': result[0],
                'api_secret': result[1],
                'additional_params': json.loads(result[2]) if result[2] else {}
            }
        return None

    def save_app_setting(self, key: str, value: str):
        """保存应用设置"""
        cursor = self.get_connection().cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO app_settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        ''', (key, value))
        self.get_connection().commit()

    def get_app_setting(self, key: str, default: str = '') -> str:
        """获取应用设置"""
        cursor = self.get_connection().cursor()
        cursor.execute('SELECT value FROM app_settings WHERE key = ?', (key,))
        result = cursor.fetchone()
        return result[0] if result else default


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

            # 解析地址获取坐标
            coordinates = self._geocode_address()
            self.progress_updated.emit(50)

            if coordinates:
                # 保存到数据库
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
        """地址解析"""
        if self.location_type == 'domestic':
            return self._amap_geocode()
        else:
            return self._osm_geocode()

    def _amap_geocode(self) -> Optional[Dict]:
        """高德地图地址解析"""
        try:
            db_manager = self.db_manager
            settings = db_manager.get_api_settings('amap')

            if settings and settings.get('api_key'):
                # 使用高德API
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
            else:
                # 使用免费的地理编码服务
                return self._nominatim_geocode()

        except Exception as e:
            logger.error(f"高德地理编码失败: {e}")
            return self._nominatim_geocode()

        return None

    def _osm_geocode(self) -> Optional[Dict]:
        """使用OpenStreetMap Nominatim进行地理编码"""
        return self._nominatim_geocode()

    def _nominatim_geocode(self) -> Optional[Dict]:
        """Nominatim地理编码（免费，无需API key）"""
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

    def stop(self):
        self._is_running = False


class BackupWorker(QThread):
    """备份工作线程"""
    backup_completed = Signal(str)
    backup_failed = Signal(str)
    progress_updated = Signal(int)

    def __init__(self, db_manager: DatabaseManager, backup_type: str = 'auto'):
        super().__init__()
        self.db_manager = db_manager
        self.backup_type = backup_type

    def run(self):
        try:
            self.progress_updated.emit(20)
            backup_path = self.db_manager.create_backup(self.backup_type)
            self.progress_updated.emit(80)
            self.backup_completed.emit(backup_path)
            self.progress_updated.emit(100)
        except Exception as e:
            self.backup_failed.emit(str(e))


class RestoreWorker(QThread):
    """恢复工作线程"""
    restore_completed = Signal(bool)
    restore_failed = Signal(str)
    progress_updated = Signal(int)

    def __init__(self, db_manager: DatabaseManager, backup_id: int, action: str = 'restore'):
        super().__init__()
        self.db_manager = db_manager
        self.backup_id = backup_id
        self.action = action

    def run(self):
        try:
            self.progress_updated.emit(30)
            if self.action == 'restore':
                success = self.db_manager.restore_backup(self.backup_id)
            else:  # rollback
                success = self.db_manager.rollback_backup(self.backup_id)

            self.progress_updated.emit(80)
            self.restore_completed.emit(success)
            self.progress_updated.emit(100)
        except Exception as e:
            self.restore_failed.emit(str(e))


class MapWidget(QWebEngineView):
    """地图显示组件"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_location = None
        self.map_type = 'normal'  # normal, satellite
        self.setMinimumSize(400, 300)

    def load_default_map(self):
        """加载默认地图"""
        html = '''
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>地图</title>
            <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
            <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
            <style>
                #map { height: 100%; width: 100%; }
                body { margin: 0; padding: 0; }
            </style>
        </head>
        <body>
            <div id="map"></div>
            <script>
                var map = L.map('map').setView([39.9042, 116.4074], 13);
                L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                    attribution: '© OpenStreetMap contributors'
                }).addTo(map);
            </script>
        </body>
        </html>
        '''
        self.setHtml(html)

    def show_location(self, lat: float, lng: float, location_type: str = 'domestic',
                      api_settings: Dict = None):
        """显示指定位置"""
        self.current_location = (lat, lng)

        if location_type == 'domestic':
            self._show_amap(lat, lng, api_settings)
        else:
            self._show_osm(lat, lng)

    def _show_amap(self, lat: float, lng: float, api_settings: Dict = None):
        """使用高德地图显示"""
        api_key = ''
        if api_settings:
            amap_settings = api_settings.get('amap', {})
            api_key = amap_settings.get('api_key', '')

        if api_key:
            html = f'''
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <title>高德地图</title>
                <style>
                    #container {{ height: 100%; width: 100%; }}
                    body {{ margin: 0; padding: 0; }}
                </style>
            </head>
            <body>
                <div id="container"></div>
                <script src="https://webapi.amap.com/maps?v=2.0&key={api_key}"></script>
                <script>
                    var map = new AMap.Map('container', {{
                        zoom: 15,
                        center: [{lng}, {lat}],
                        layers: [new AMap.TileLayer()]
                    }});
                    
                    var marker = new AMap.Marker({{
                        position: [{lng}, {lat}],
                        title: '目标位置'
                    }});
                    map.add(marker);
                </script>
            </body>
            </html>
            '''
        else:
            # 没有API key，使用OpenStreetMap
            self._show_osm(lat, lng)

    def _show_osm(self, lat: float, lng: float):
        """使用OpenStreetMap显示"""
        tile_url = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'
        if self.map_type == 'satellite':
            tile_url = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'

        html = f'''
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>OpenStreetMap</title>
            <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
            <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
            <style>
                #map {{ height: 100%; width: 100%; }}
                body {{ margin: 0; padding: 0; }}
            </style>
        </head>
        <body>
            <div id="map"></div>
            <script>
                var map = L.map('map').setView([{lat}, {lng}], 15);
                L.tileLayer('{tile_url}', {{
                    attribution: '© OpenStreetMap contributors'
                }}).addTo(map);
                
                L.marker([{lat}, {lng}]).addTo(map)
                    .bindPopup('目标位置')
                    .openPopup();
            </script>
        </body>
        </html>
        '''
        self.setHtml(html)


class StreetViewWidget(QWebEngineView):
    """街景显示组件"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 300)

    def show_street_view(self, lat: float, lng: float, location_type: str = 'domestic',
                         api_settings: Dict = None):
        """显示街景"""
        if location_type == 'domestic':
            self._show_baidu_streetview(lat, lng, api_settings)
        else:
            self._show_google_streetview(lat, lng)

    def _show_baidu_streetview(self, lat: float, lng: float, api_settings: Dict = None):
        """使用百度街景"""
        ak = ''
        if api_settings:
            baidu_settings = api_settings.get('baidu', {})
            ak = baidu_settings.get('api_key', '')

        if ak:
            html = f'''
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <title>百度街景</title>
                <style>
                    #panorama {{ height: 100%; width: 100%; }}
                    body {{ margin: 0; padding: 0; }}
                </style>
                <script src="https://api.map.baidu.com/api?v=3.0&ak={ak}"></script>
            </head>
            <body>
                <div id="panorama"></div>
                <script>
                    var panorama = new BMap.Panorama('panorama', {{
                        position: new BMap.Point({lng}, {lat})
                    }});
                </script>
            </body>
            </html>
            '''
        else:
            html = f'''
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <title>街景不可用</title>
                <style>
                    body {{ 
                        display: flex; 
                        justify-content: center; 
                        align-items: center; 
                        height: 100%;
                        margin: 0;
                        font-family: Arial, sans-serif;
                        background: #f0f0f0;
                    }}
                    .notice {{
                        text-align: center;
                        padding: 20px;
                        background: white;
                        border-radius: 10px;
                        box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                    }}
                </style>
            </head>
            <body>
                <div class="notice">
                    <h3>街景需要配置百度地图API Key</h3>
                    <p>请在设置中配置百度地图API Key以使用街景功能</p>
                </div>
            </body>
            </html>
            '''
        self.setHtml(html)

    def _show_google_streetview(self, lat: float, lng: float):
        """使用Google街景（仅国外）"""
        html = f'''
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
                function initialize() {{
                    var panorama = new google.maps.StreetViewPanorama(
                        document.getElementById('street-view'), {{
                            position: {{lat: {lat}, lng: {lng}}},
                            pov: {{heading: 165, pitch: 0}},
                            zoom: 1
                        }});
                }}
            </script>
            <script src="https://maps.googleapis.com/maps/api/js?key=&callback=initialize" async defer></script>
        </body>
        </html>
        '''
        self.setHtml(html)


class BackupDialog(QDialog):
    """数据库备份恢复对话框"""

    def __init__(self, db_manager: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db_manager = db_manager
        self.setWindowTitle("数据库备份管理")
        self.setMinimumSize(800, 600)
        self._init_ui()
        self._load_backup_list()

    def _init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)

        # 筛选区域
        filter_group = QGroupBox("筛选条件")
        filter_layout = QHBoxLayout(filter_group)

        # 时间范围筛选
        filter_layout.addWidget(QLabel("开始时间:"))
        self.start_time_edit = QDateTimeEdit()
        self.start_time_edit.setCalendarPopup(True)
        self.start_time_edit.setDateTime(QDateTime.currentDateTime().addMonths(-1))
        filter_layout.addWidget(self.start_time_edit)

        filter_layout.addWidget(QLabel("结束时间:"))
        self.end_time_edit = QDateTimeEdit()
        self.end_time_edit.setCalendarPopup(True)
        self.end_time_edit.setDateTime(QDateTime.currentDateTime())
        filter_layout.addWidget(self.end_time_edit)

        # 备份类型筛选
        filter_layout.addWidget(QLabel("备份类型:"))
        self.type_combo = QComboBox()
        self.type_combo.addItems(['全部', '自动', '手动', '回滚'])
        filter_layout.addWidget(self.type_combo)

        # 筛选按钮
        filter_btn = QPushButton("筛选")
        filter_btn.clicked.connect(self._load_backup_list)
        filter_layout.addWidget(filter_btn)

        layout.addWidget(filter_group)

        # 备份列表表格
        self.backup_table = QTableWidget()
        self.backup_table.setColumnCount(7)
        self.backup_table.setHorizontalHeaderLabels([
            '备份时间', '备份类型', '文件名', '文件大小', '数据库版本',
            '记录数量', '操作'
        ])
        self.backup_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.backup_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.backup_table.itemClicked.connect(self._show_backup_details)
        layout.addWidget(self.backup_table)

        # 详细信息预览
        detail_group = QGroupBox("备份详细信息")
        detail_layout = QVBoxLayout(detail_group)
        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setMaximumHeight(150)
        detail_layout.addWidget(self.detail_text)
        layout.addWidget(detail_group)

        # 按钮区域
        button_layout = QHBoxLayout()

        # 手动备份按钮
        manual_backup_btn = QPushButton("手动备份")
        manual_backup_btn.clicked.connect(self._manual_backup)
        button_layout.addWidget(manual_backup_btn)

        # 恢复按钮
        restore_btn = QPushButton("恢复选中备份")
        restore_btn.clicked.connect(self._restore_backup)
        button_layout.addWidget(restore_btn)

        # 回滚按钮
        rollback_btn = QPushButton("回滚到选中备份")
        rollback_btn.clicked.connect(self._rollback_backup)
        button_layout.addWidget(rollback_btn)

        # 设置最大备份数
        button_layout.addWidget(QLabel("最大备份数:"))
        self.max_backup_spin = QSpinBox()
        self.max_backup_spin.setRange(5, 100)
        self.max_backup_spin.setValue(self.db_manager.max_backups)
        self.max_backup_spin.valueChanged.connect(self._update_max_backups)
        button_layout.addWidget(self.max_backup_spin)

        button_layout.addStretch()

        # 关闭按钮
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

    def _load_backup_list(self):
        """加载备份列表"""
        backup_type = self.type_combo.currentText()
        if backup_type == '全部':
            backup_type = None
        elif backup_type == '自动':
            backup_type = 'auto'
        elif backup_type == '手动':
            backup_type = 'manual'
        elif backup_type == '回滚':
            backup_type = 'rollback'

        start_time = self.start_time_edit.dateTime().toString(Qt.ISODate)
        end_time = self.end_time_edit.dateTime().toString(Qt.ISODate)

        backups = self.db_manager.get_backup_list(backup_type, start_time, end_time)

        self.backup_table.setRowCount(len(backups))
        for i, backup in enumerate(backups):
            # 备份时间
            time_item = QTableWidgetItem(backup['backup_time'])
            self.backup_table.setItem(i, 0, time_item)

            # 备份类型
            type_map = {'auto': '自动', 'manual': '手动', 'rollback': '回滚'}
            type_item = QTableWidgetItem(type_map.get(backup['backup_type'], backup['backup_type']))
            self.backup_table.setItem(i, 1, type_item)

            # 文件名
            file_item = QTableWidgetItem(backup['file_name'])
            self.backup_table.setItem(i, 2, file_item)

            # 文件大小
            size_mb = backup['file_size'] / (1024 * 1024)
            size_item = QTableWidgetItem(f"{size_mb:.2f} MB")
            self.backup_table.setItem(i, 3, size_item)

            # 版本
            version_item = QTableWidgetItem(backup['db_version'] or 'N/A')
            self.backup_table.setItem(i, 4, version_item)

            # 记录数量
            count_item = QTableWidgetItem(str(backup['record_count'] or 0))
            self.backup_table.setItem(i, 5, count_item)

            # 操作按钮
            btn_widget = QWidget()
            btn_layout = QHBoxLayout(btn_widget)
            btn_layout.setContentsMargins(2, 2, 2, 2)

            detail_btn = QPushButton("详情")
            detail_btn.clicked.connect(lambda checked, b=backup: self._show_backup_details(b))
            btn_layout.addWidget(detail_btn)

            self.backup_table.setCellWidget(i, 6, btn_widget)

    def _show_backup_details(self, backup_or_item):
        """显示备份详细信息"""
        if isinstance(backup_or_item, QTableWidgetItem):
            row = backup_or_item.row()
            # 从表格获取备份数据
            # 这里简化处理，实际应存储完整的备份数据            backup = {
                'backup_time': self.backup_table.item(row, 0).text(),
                'backup_type': self.backup_table.item(row, 1).text(),
                'file_name': self.backup_table.item(row, 2).text(),
                'file_size': self.backup_table.item(row, 3).text(),
                'db_version': self.backup_table.item(row, 4).text(),
                'record_count': self.backup_table.item(row, 5).text(),
            }
        else:
            backup = backup_or_item

        detail_text = f"""
备份时间: {backup.get('backup_time', 'N/A')}
备份类型: {backup.get('backup_type', 'N/A')}
文件名: {backup.get('file_name', 'N/A')}
文件大小: {backup.get('file_size', 'N/A')}
数据库版本: {backup.get('db_version', 'N/A')}
记录数量: {backup.get('record_count', 'N/A')}
日期范围: {backup.get('date_range_start', 'N/A')} 至 {backup.get('date_range_end', 'N/A')}
        """
        self.detail_text.setText(detail_text)

    def _manual_backup(self):
        """手动备份"""
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        self.backup_worker = BackupWorker(self.db_manager, 'manual')
        self.backup_worker.progress_updated.connect(self.progress_bar.setValue)
        self.backup_worker.backup_completed.connect(self._on_backup_completed)
        self.backup_worker.backup_failed.connect(self._on_backup_failed)
        self.backup_worker.start()

    def _restore_backup(self):
        """恢复备份"""
        current_row = self.backup_table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "警告", "请先选择要恢复的备份")
            return

        backup_data = self._get_backup_data_from_row(current_row)
        if not backup_data:
            return

        reply = QMessageBox.question(
            self, "确认恢复",
            f"确定要恢复到备份 {backup_data['backup_time']} 吗？\n恢复前会自动备份当前数据。",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self._execute_restore(backup_data['id'], 'restore')

    def _rollback_backup(self):
        """回滚到备份"""
        current_row = self.backup_table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "警告", "请先选择要回滚的备份")
            return

        backup_data = self._get_backup_data_from_row(current_row)
        if not backup_data:
            return

        reply = QMessageBox.question(
            self, "确认回滚",
            f"确定要回滚到备份 {backup_data['backup_time']} 吗？\n回滚前会自动备份当前数据。",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self._execute_restore(backup_data['id'], 'rollback')

    def _get_backup_data_from_row(self, row: int) -> Optional[Dict]:
        """从表格行获取备份数据"""
        try:
            # 获取备份ID
            cursor = self.db_manager.get_connection().cursor()
            cursor.execute('''
                SELECT id FROM backup_records 
                WHERE backup_time = ? AND file_name = ?
                ORDER BY backup_time DESC LIMIT 1
            ''', (
                self.backup_table.item(row, 0).text(),
                self.backup_table.item(row, 2).text()
            ))
            result = cursor.fetchone()
            if result:
                return {
                    'id': result[0],
                    'backup_time': self.backup_table.item(row, 0).text(),
                    'backup_type': self.backup_table.item(row, 1).text(),
                    'file_name': self.backup_table.item(row, 2).text()
                }
        except Exception as e:
            logger.error(f"获取备份数据失败: {e}")
        return None

    def _execute_restore(self, backup_id: int, action: str):
        """执行恢复操作"""
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        self.restore_worker = RestoreWorker(self.db_manager, backup_id, action)
        self.restore_worker.progress_updated.connect(self.progress_bar.setValue)
        self.restore_worker.restore_completed.connect(self._on_restore_completed)
        self.restore_worker.restore_failed.connect(self._on_restore_failed)
        self.restore_worker.start()

    def _on_backup_completed(self, backup_path: str):
        """备份完成"""
        self.progress_bar.setVisible(False)
        QMessageBox.information(self, "成功", f"备份已完成: {backup_path}")
        self._load_backup_list()

    def _on_backup_failed(self, error: str):
        """备份失败"""
        self.progress_bar.setVisible(False)
        QMessageBox.critical(self, "错误", f"备份失败: {error}")

    def _on_restore_completed(self, success: bool):
        """恢复完成"""
        self.progress_bar.setVisible(False)
        if success:
            QMessageBox.information(self, "成功", "数据库恢复成功，正在重新初始化...")
            # 通知主窗口刷新
            if self.parent():
                self.parent().statusBar().showMessage("数据库已恢复，界面已刷新", 5000)
        self._load_backup_list()

    def _on_restore_failed(self, error: str):
        """恢复失败"""
        self.progress_bar.setVisible(False)
        QMessageBox.critical(self, "错误", f"恢复失败: {error}")

    def _update_max_backups(self, value: int):
        """更新最大备份数"""
        self.db_manager.max_backups = value
        self.db_manager.save_app_setting('max_backups', str(value))


class SettingsDialog(QDialog):
    """设置对话框"""

    def __init__(self, db_manager: DatabaseManager, parent=None):
        super().__init__(parent)
        self.db_manager = db_manager
        self.setWindowTitle("设置")
        self.setMinimumSize(500, 400)
        self._init_ui()
        self._load_settings()

    def _init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)

        # 标签页
        tab_widget = QTabWidget()

        # API设置标签
        api_tab = QWidget()
        api_layout = QVBoxLayout(api_tab)

        # 高德地图设置
        amap_group = QGroupBox("高德地图 (国内定位)")
        amap_layout = QHBoxLayout(amap_group)
        amap_layout.addWidget(QLabel("API Key:"))
        self.amap_key_edit = QLineEdit()
        self.amap_key_edit.setPlaceholderText("输入高德地图Web服务API Key")
        amap_layout.addWidget(self.amap_key_edit)
        api_layout.addWidget(amap_group)

        # 百度地图设置
        baidu_group = QGroupBox("百度地图 (街景)")
        baidu_layout = QHBoxLayout(baidu_group)
        baidu_layout.addWidget(QLabel("API Key (AK):"))
        self.baidu_ak_edit = QLineEdit()
        self.baidu_ak_edit.setPlaceholderText("输入百度地图API Key")
        baidu_layout.addWidget(self.baidu_ak_edit)
        api_layout.addWidget(baidu_group)

        # Google地图设置
        google_group = QGroupBox("Google地图 (国外街景)")
        google_layout = QHBoxLayout(google_group)
        google_layout.addWidget(QLabel("API Key:"))
        self.google_key_edit = QLineEdit()
        self.google_key_edit.setPlaceholderText("输入Google Maps API Key")
        google_layout.addWidget(self.google_key_edit)
        api_layout.addWidget(google_group)

        api_layout.addStretch()
        tab_widget.addTab(api_tab, "API设置")

        # 应用设置标签
        app_tab = QWidget()
        app_layout = QVBoxLayout(app_tab)

        # 备份设置
        backup_group = QGroupBox("备份设置")
        backup_layout = QHBoxLayout(backup_group)
        backup_layout.addWidget(QLabel("最大备份数量:"))
        self.max_backup_spin = QSpinBox()
        self.max_backup_spin.setRange(5, 100)
        self.max_backup_spin.setValue(30)
        backup_layout.addWidget(self.max_backup_spin)
        app_layout.addWidget(backup_group)

        # 调试模式
        debug_group = QGroupBox("调试设置")
        debug_layout = QHBoxLayout(debug_group)
        self.debug_check = QCheckBox("启用调试模式")
        debug_layout.addWidget(self.debug_check)
        app_layout.addWidget(debug_group)

        app_layout.addStretch()
        tab_widget.addTab(app_tab, "应用设置")

        layout.addWidget(tab_widget)

        # 按钮
        button_layout = QHBoxLayout()
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._save_settings)
        button_layout.addWidget(save_btn)

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)

    def _load_settings(self):
        """加载设置"""
        # 加载API设置
        amap_settings = self.db_manager.get_api_settings('amap')
        if amap_settings:
            self.amap_key_edit.setText(amap_settings.get('api_key', ''))

        baidu_settings = self.db_manager.get_api_settings('baidu')
        if baidu_settings:
            self.baidu_ak_edit.setText(baidu_settings.get('api_key', ''))

        google_settings = self.db_manager.get_api_settings('google')
        if google_settings:
            self.google_key_edit.setText(google_settings.get('api_key', ''))

        # 加载应用设置
        max_backups = self.db_manager.get_app_setting('max_backups', '30')
        self.max_backup_spin.setValue(int(max_backups))

        debug_mode = self.db_manager.get_app_setting('debug_mode', 'false')
        self.debug_check.setChecked(debug_mode.lower() == 'true')

    def _save_settings(self):
        """保存设置"""
        # 保存API设置
        if self.amap_key_edit.text():
            self.db_manager.save_api_settings('amap', {
                'api_key': self.amap_key_edit.text()
            })

        if self.baidu_ak_edit.text():
            self.db_manager.save_api_settings('baidu', {
                'api_key': self.baidu_ak_edit.text()
            })

        if self.google_key_edit.text():
            self.db_manager.save_api_settings('google', {
                'api_key': self.google_key_edit.text()
            })

        # 保存应用设置
        self.db_manager.save_app_setting('max_backups', str(self.max_backup_spin.value()))
        self.db_manager.save_app_setting('debug_mode', str(self.debug_check.isChecked()).lower())

        # 更新全局调试模式
        global DEBUG_MODE
        DEBUG_MODE = self.debug_check.isChecked()

        self.accept()
        QMessageBox.information(self, "成功", "设置已保存")


class MainWindow(QMainWindow):
    """主窗口"""

    def __init__(self):
        super().__init__()
        self.db_manager = DatabaseManager()
        self.setWindowTitle("地址定位与街景查看系统")
        self.setMinimumSize(1200, 800)

        # 加载图标
        self._load_icon()

        # 初始化UI
        self._init_ui()

        # 加载设置
        self._load_app_settings()

        # 启动自动备份定时器
        self._start_auto_backup()

        # 显示状态
        self.statusBar().showMessage("系统就绪", 3000)

    def _load_icon(self):
        """加载图标"""
        icon_path = Path("icon.ico")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

    def _init_ui(self):
        """初始化UI"""
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        # 搜索区域
        search_widget = QWidget()
        search_layout = QHBoxLayout(search_widget)
        search_layout.setContentsMargins(0, 0, 0, 0)

        # 地址输入
        search_layout.addWidget(QLabel("地址:"))
        self.address_input = QLineEdit()
        self.address_input.setPlaceholderText("输入地址进行搜索...")
        self.address_input.returnPressed.connect(self._search_location)
        search_layout.addWidget(self.address_input, 2)

        # 区域选择
        search_layout.addWidget(QLabel("区域:"))
        self.location_type_combo = QComboBox()
        self.location_type_combo.addItems(['国内', '国外'])
        search_layout.addWidget(self.location_type_combo)

        # 搜索按钮
        self.search_btn = QPushButton("搜索")
        self.search_btn.clicked.connect(self._search_location)
        search_layout.addWidget(self.search_btn)

        # 地图类型切换
        self.map_type_combo = QComboBox()
        self.map_type_combo.addItems(['标准地图', '卫星地图'])
        self.map_type_combo.currentTextChanged.connect(self._change_map_type)
        search_layout.addWidget(self.map_type_combo)

        main_layout.addWidget(search_widget)

        # 地图和街景分割区域
        splitter = QSplitter(Qt.Horizontal)

        # 地图视图
        map_widget_container = QWidget()
        map_layout = QVBoxLayout(map_widget_container)
        map_layout.setContentsMargins(0, 0, 0, 0)

        map_label = QLabel("地图视图")
        map_label.setStyleSheet("font-weight: bold; padding: 2px;")
        map_layout.addWidget(map_label)

        self.map_view = MapWidget()
        self.map_view.load_default_map()
        map_layout.addWidget(self.map_view)

        splitter.addWidget(map_widget_container)

        # 街景视图
        street_widget_container = QWidget()
        street_layout = QVBoxLayout(street_widget_container)
        street_layout.setContentsMargins(0, 0, 0, 0)

        street_label = QLabel("街景视图")
        street_label.setStyleSheet("font-weight: bold; padding: 2px;")
        street_layout.addWidget(street_label)

        self.street_view = StreetViewWidget()
        street_layout.addWidget(self.street_view)

        splitter.addWidget(street_widget_container)

        # 设置初始分割比例
        splitter.setSizes([600, 600])

        main_layout.addWidget(splitter, 1)

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

        # 备份管理
        backup_action = QAction("数据库备份管理(&B)", self)
        backup_action.triggered.connect(self._open_backup_dialog)
        file_menu.addAction(backup_action)

        file_menu.addSeparator()

        # 退出
        exit_action = QAction("退出(&Q)", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # 工具菜单
        tools_menu = menubar.addMenu("工具(&T)")

        # 设置
        settings_action = QAction("设置(&S)", self)
        settings_action.triggered.connect(self._open_settings_dialog)
        tools_menu.addAction(settings_action)

        # 清除历史
        clear_history_action = QAction("清除搜索历史(&C)", self)
        clear_history_action.triggered.connect(self._clear_history)
        tools_menu.addAction(clear_history_action)

        # 帮助菜单
        help_menu = menubar.addMenu("帮助(&H)")

        about_action = QAction("关于(&A)", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

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

        # 禁用搜索按钮
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
        self.map_view.show_location(
            result['lat'], result['lng'],
            result['location_type'],
            self._get_api_settings()
        )

        # 更新街景
        self.street_view.show_street_view(
            result['lat'], result['lng'],
            result['location_type'],
            self._get_api_settings()
        )

        self.statusBar().showMessage(f"已定位: {result['display_name']}", 5000)

    def _on_search_failed(self, error: str):
        """搜索失败"""
        self.progress_bar.setVisible(False)
        self.search_btn.setEnabled(True)
        self.statusBar().showMessage(f"搜索失败: {error}", 5000)

    def _change_map_type(self, map_type: str):
        """切换地图类型"""
        if map_type == '卫星地图':
            self.map_view.map_type = 'satellite'
        else:
            self.map_view.map_type = 'normal'

        # 如果有当前位置，重新加载
        if self.map_view.current_location:
            lat, lng = self.map_view.current_location
            location_type = 'domestic' if self.location_type_combo.currentText() == '国内' else 'international'
            self.map_view.show_location(lat, lng, location_type, self._get_api_settings())

    def _get_api_settings(self) -> Dict:
        """获取API设置"""
        settings = {}
        for service in ['amap', 'baidu', 'google']:
            api_data = self.db_manager.get_api_settings(service)
            if api_data:
                settings[service] = api_data
        return settings

    def _open_backup_dialog(self):
        """打开备份管理对话框"""
        dialog = BackupDialog(self.db_manager, self)
        dialog.exec()

        # 对话框关闭后刷新界面
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
            "地址定位与街景查看系统 v1.0\n\n"
            "功能：输入地址查看地图位置和街景\n"
            "支持国内外多种地图服务\n\n"
            "© 2024 MapLocator"
        )

    def _start_auto_backup(self):
        """启动自动备份"""
        # 启动时自动备份
        auto_backup = BackupWorker(self.db_manager, 'auto')
        auto_backup.backup_completed.connect(
            lambda path: self.statusBar().showMessage(f"自动备份完成: {path}", 3000)
        )
        auto_backup.backup_failed.connect(
            lambda error: logger.error(f"自动备份失败: {error}")
        )
        auto_backup.start()

        # 设置定时备份（每24小时）
        self.backup_timer = QTimer()
        self.backup_timer.timeout.connect(
            lambda: BackupWorker(self.db_manager, 'auto').start()
        )
        self.backup_timer.start(24 * 60 * 60 * 1000)  # 24小时

    def _load_app_settings(self):
        """加载应用设置"""
        # 加载窗口状态
        settings = QSettings("MapLocator", "MainWindow")
        geometry = settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        state = settings.value("windowState")
        if state:
            self.restoreState(state)

        # 加载其他设置
        debug_mode = self.db_manager.get_app_setting('debug_mode', 'false')
        global DEBUG_MODE
        DEBUG_MODE = debug_mode.lower() == 'true'

    def closeEvent(self, event):
        """关闭事件"""
        # 保存窗口状态
        settings = QSettings("MapLocator", "MainWindow")
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("windowState", self.saveState())

        # 保存其他设置
        self.db_manager.save_app_setting(
            'location_type',
            self.location_type_combo.currentText()
        )
        self.db_manager.save_app_setting(
            'map_type',
            self.map_type_combo.currentText()
        )

        # 关闭数据库连接
        if self.db_manager.connection:
            self.db_manager.connection.close()

        event.accept()


def main():
    """主函数"""
    try:
        # 创建应用
        app = QApplication(sys.argv)
        app.setApplicationName("MapLocator")
        app.setOrganizationName("MapLocator")

        # 设置应用程序样式
        app.setStyle('Fusion')

        # 创建主窗口
        window = MainWindow()
        window.show()

        # 运行应用
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