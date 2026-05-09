"""课程视频下载工具 - GUI界面 (PyQt5)"""

import os
import sys
import json
from datetime import datetime

def _clear_dead_proxy_env():
    dead_proxy_values = {"http://127.0.0.1:9", "https://127.0.0.1:9"}
    for key in (
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
        "GIT_HTTP_PROXY", "GIT_HTTPS_PROXY",
        "http_proxy", "https_proxy", "all_proxy",
    ):
        if os.environ.get(key, "").lower() in dead_proxy_values:
            os.environ.pop(key, None)


_clear_dead_proxy_env()

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QListWidget, QListWidgetItem, QPushButton,
    QProgressBar, QTextEdit, QCheckBox, QGroupBox, QGridLayout,
    QSplitter, QMessageBox, QLineEdit, QFileDialog, QTabWidget,
    QFormLayout, QAbstractItemView, QTreeWidget, QTreeWidgetItem,
    QHeaderView
)
from PyQt5.QtCore import Qt, pyqtSignal, QObject, QThread
from PyQt5.QtGui import QFont

from crawler import CourseCrawler
from downloader import VideoDownloader
from transcriber import Transcriber
from summarizer import Summarizer
from config import load_config, save_config
from performance_utils import MemoryCache

# 用名字存已下载文件，跨 worker 共享
_downloaded_files = []  # list of paths


class WorkerSignals(QObject):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    log = pyqtSignal(str)
    item_start = pyqtSignal(int, str)    # index, message
    item_done = pyqtSignal(int, str)     # index, path
    item_fail = pyqtSignal(int, str)     # index, reason


class CrawlerWorker(QThread):
    """后台工作线程"""

    def __init__(self, task, **kwargs):
        super().__init__()
        self.task = task
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    def run(self):
        try:
            if self.task == "semesters":
                c = CourseCrawler()
                self.signals.finished.emit({"semesters": c.get_semesters()})

            elif self.task == "courses":
                c = CourseCrawler()
                self.signals.finished.emit({
                    "courses": c.get_all_courses(self.kwargs["xq_code"])
                })

            elif self.task == "calendar":
                c = CourseCrawler()
                self.signals.finished.emit({
                    "calendar": c.get_teaching_calendar(self.kwargs["c_id"])
                })

            elif self.task == "batch_download":
                self._run_batch_download()

            elif self.task == "batch_transcribe":
                self._run_batch_transcribe()

            elif self.task == "summarize":
                sm = Summarizer()
                text = self.kwargs["text"]
                result = sm.summarize(
                    text,
                    progress_callback=lambda pct: self.signals.progress.emit(
                        int(pct * 100), "总结中..."),
                )
                out = self.kwargs.get("output_path")
                if out:
                    sm.save_summary(result, out)
                self.signals.finished.emit({"summary": result, "output_path": out})

        except Exception as e:
            self.signals.error.emit(str(e))

    # ---- 批量下载 ----

    def _run_batch_download(self):
        items = self.kwargs["items"]       # list of {sched_id, label, output_path, audio_only}
        stream_key = self.kwargs.get("stream_key", "course_url")
        user_id = self.kwargs.get("user_id", "170179")

        crawler = CourseCrawler()
        dl = VideoDownloader(crawler)
        total = len(items)
        audio_only_batch = any(item.get("audio_only") for item in items)

        for i, item in enumerate(items):
            self.signals.log.emit(
                f"[{i+1}/{total}] 获取视频流: {os.path.basename(item['output_path'])}")

            self.signals.item_start.emit(i, "获取视频流")
            stream_info = crawler.get_stream_info(
                item["sched_id"], user_level=1, user_id=user_id)
            if not stream_info:
                self.signals.item_fail.emit(i, "无法获取视频流信息")
                continue

            m3u8_url = stream_info.get(stream_key, "")
            if not m3u8_url or m3u8_url == "noVideo":
                self.signals.item_fail.emit(i, f"该画面无视频")
                continue

            self.signals.log.emit(f"[{i+1}/{total}] 开始下载...")
            self.signals.item_start.emit(i, "下载中")
            last_pct = [0]

            def progress_cb(pct, idx=i, tot=total):
                p = int(pct * 100)
                if p > last_pct[0]:
                    last_pct[0] = p
                overall = int((idx / tot + pct / tot) * 100)
                self.signals.progress.emit(
                    overall, f"[{idx+1}/{tot}] 下载中 {p}%")

            try:
                if item.get("audio_only"):
                    result = dl.download_audio_only(m3u8_url, item["output_path"], progress_cb)
                else:
                    result = dl.download_m3u8(m3u8_url, item["output_path"], progress_cb)

                if result:
                    _downloaded_files.append(result)
                    self.signals.item_done.emit(i, result)
                else:
                    self.signals.item_fail.emit(i, "下载失败")
            except Exception as e:
                self.signals.item_fail.emit(i, str(e))

        self.signals.progress.emit(100, "批量下载完成")
        self.signals.finished.emit({
            "batch": "download_complete",
            "audio_only": audio_only_batch,
        })

    # ---- 批量转写 ----

    def _run_batch_transcribe(self):
        files = self.kwargs["files"]       # list of audio file paths
        model_size = self.kwargs.get("model_size", "large-v3-turbo")
        out_dir = self.kwargs.get("out_dir", "")
        os.makedirs(out_dir, exist_ok=True)

        tr = Transcriber()
        total = len(files)

        for i, audio_path in enumerate(files):
            name = os.path.basename(audio_path)
            self.signals.log.emit(f"[{i+1}/{total}] 转写: {name}")
            base = os.path.splitext(name)[0]
            out_path = os.path.join(out_dir, base + "_transcript.json")

            last_pct = [0]

            def progress_cb(pct, idx=i, tot=total):
                p = int(pct * 100)
                overall = int((idx / tot + pct / tot) * 100)
                self.signals.progress.emit(overall, f"[{idx+1}/{tot}] 转写中 {p}%")

            try:
                result, saved = tr.transcribe_to_file(
                    audio_path, output_path=out_path,
                    progress_callback=progress_cb, model_size=model_size)
                self.signals.item_done.emit(i, saved)
            except Exception as e:
                self.signals.item_fail.emit(i, str(e))

        self.signals.progress.emit(100, "批量转写完成")
        self.signals.finished.emit({"batch": "transcribe_complete"})


# ================================================================
# 主窗口
# ================================================================

class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.cfg = load_config()
        self.courses = []
        self.calendar = []
        self.current_course = None
        self.transcript_result = None
        self.worker = None
        self.semester_cache = MemoryCache()
        self.course_cache = MemoryCache()
        self.calendar_cache = MemoryCache()
        self._init_ui()
        self._load_semesters()

    # ========================= UI 搭建 =========================

    def _init_ui(self):
        self.setWindowTitle("课程回放下载工具")
        self.setMinimumSize(1250, 780)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 8)

        # ---- 左侧 ----
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # 学期
        sem = QGroupBox("学期选择")
        sl = QHBoxLayout(sem)
        self.sem_combo = QComboBox()
        self.sem_combo.currentIndexChanged.connect(self._on_semester_changed)
        sl.addWidget(self.sem_combo)
        left_layout.addWidget(sem)

        # 课程
        cg = QGroupBox("课程列表")
        cl = QVBoxLayout(cg)
        self.course_list = QListWidget()
        self.course_list.setMinimumHeight(180)
        self.course_list.itemClicked.connect(self._on_course_selected)
        cl.addWidget(self.course_list)
        left_layout.addWidget(cg)

        # 回放（多选）
        rg = QGroupBox("回放列表（可多选）")
        rl = QVBoxLayout(rg)
        # 顶部按钮行
        rbtn = QHBoxLayout()
        self.select_all_btn = QPushButton("全选")
        self.select_all_btn.clicked.connect(lambda: self.replay_list.selectAll())
        rbtn.addWidget(self.select_all_btn)
        self.deselect_btn = QPushButton("取消")
        self.deselect_btn.clicked.connect(lambda: self.replay_list.clearSelection())
        rbtn.addWidget(self.deselect_btn)
        self.replay_count_label = QLabel("已选: 0")
        rbtn.addWidget(self.replay_count_label)
        rbtn.addStretch()
        rl.addLayout(rbtn)
        # 列表
        self.replay_list = QListWidget()
        self.replay_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.replay_list.setMinimumHeight(200)
        self.replay_list.itemSelectionChanged.connect(self._on_replay_selection_changed)
        rl.addWidget(self.replay_list)
        left_layout.addWidget(rg)

        # ---- 右侧 ----
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()
        tabs = self.tabs

        # ===== Tab 1: 下载 =====
        dl_tab = QWidget()
        dl_layout = QVBoxLayout(dl_tab)

        # 画面选择
        sg = QGroupBox("视频画面")
        slayout = QGridLayout(sg)
        self.stream_combo = QComboBox()
        self.stream_combo.addItems([
            "课件画面 (course_url)",
            "教师画面 (teacher_url)",
            "学生画面 (student_url)",
            "教师特写 (teacher_closeup_url)",
            "学生特写 (student_closeup_url)",
        ])
        slayout.addWidget(QLabel("选择画面:"), 0, 0)
        slayout.addWidget(self.stream_combo, 0, 1)
        self.audio_only_cb = QCheckBox("仅下载音频(m4a)")
        self.audio_only_cb.stateChanged.connect(self._update_download_button_text)
        slayout.addWidget(self.audio_only_cb, 1, 0, 1, 2)
        dl_layout.addWidget(sg)

        # 路径
        pg = QGroupBox("保存设置")
        pl = QHBoxLayout(pg)
        self.path_edit = QLineEdit(self.cfg.get("download_dir", ""))
        self.path_edit.setPlaceholderText("保存目录...")
        pl.addWidget(self.path_edit)
        pb = QPushButton("浏览")
        pb.clicked.connect(lambda: self.path_edit.setText(
            QFileDialog.getExistingDirectory(self, "选择下载目录") or self.path_edit.text()))
        pl.addWidget(pb)
        dl_layout.addWidget(pg)

        # 按钮
        bl = QHBoxLayout()
        self.dl_btn = QPushButton("下载选中视频")
        self.dl_btn.setMinimumHeight(36)
        self.dl_btn.clicked.connect(self._start_download_from_options)
        self.dl_btn.setEnabled(False)
        bl.addWidget(self.dl_btn)

        self.dl_audio_btn = QPushButton("下载选中 (仅音频)")
        self.dl_audio_btn.clicked.connect(lambda: self._start_batch_download(audio_only=True))
        self.dl_audio_btn.setEnabled(False)
        self.dl_audio_btn.hide()
        dl_layout.addLayout(bl)

        # 进度
        self.progress_bar = QProgressBar()
        dl_layout.addWidget(self.progress_bar)
        self.progress_label = QLabel("")
        dl_layout.addWidget(self.progress_label)

        # 任务队列
        self.task_tree = QTreeWidget()
        self.task_tree.setHeaderLabels(["状态", "文件名", "备注"])
        self.task_tree.setRootIsDecorated(False)
        self.task_tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.task_tree.setMaximumHeight(130)
        dl_layout.addWidget(QLabel("下载队列:"))
        dl_layout.addWidget(self.task_tree)
        dl_layout.addStretch()
        tabs.addTab(dl_tab, "下载")

        # ===== Tab 2: 转写 =====
        tr_tab = QWidget()
        tr_layout = QVBoxLayout(tr_tab)

        tf = QFormLayout()
        self.audio_dir_edit = QLineEdit(self.cfg.get("audio_dir", ""))
        self.audio_dir_edit.setPlaceholderText("选择音频所在目录...")
        ar = QHBoxLayout()
        ar.addWidget(self.audio_dir_edit)
        ab = QPushButton("浏览目录")
        ab.clicked.connect(self._browse_audio_dir)
        ar.addWidget(ab)
        tf.addRow("音频目录:", ar)

        self.tr_out_dir_edit = QLineEdit(self.cfg.get("transcript_dir", ""))
        self.tr_out_dir_edit.setPlaceholderText("转写输出目录...")
        odr = QHBoxLayout()
        odr.addWidget(self.tr_out_dir_edit)
        odb = QPushButton("浏览目录")
        odb.clicked.connect(self._browse_transcript_out_dir)
        odr.addWidget(odb)
        tf.addRow("输出目录:", odr)

        self.model_combo = QComboBox()
        self.model_combo.addItems(["tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"])
        idx = self.model_combo.findText(self.cfg.get("whisper_model", "large-v3-turbo"))
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)
        tf.addRow("Whisper模型:", self.model_combo)

        self.lang_combo = QComboBox()
        self.lang_combo.addItems(["zh", "en", "auto"])
        idx = self.lang_combo.findText(self.cfg.get("whisper_language", "zh"))
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)
        tf.addRow("语言:", self.lang_combo)

        self.device_combo = QComboBox()
        self.device_combo.addItems(["auto", "cuda", "cpu"])
        idx = self.device_combo.findText(self.cfg.get("whisper_device", "auto"))
        if idx >= 0:
            self.device_combo.setCurrentIndex(idx)
        self.device_combo.currentTextChanged.connect(self._on_device_changed)
        tf.addRow("设备:", self.device_combo)
        tr_layout.addLayout(tf)

        # 文件列表
        tr_layout.addWidget(QLabel("待转写文件:"))
        self.tr_file_list = QListWidget()
        self.tr_file_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tr_file_list.setMaximumHeight(130)
        tr_layout.addWidget(self.tr_file_list)

        tr_btn_row = QHBoxLayout()
        self.refresh_audio_btn = QPushButton("刷新列表")
        self.refresh_audio_btn.clicked.connect(self._refresh_audio_list)
        tr_btn_row.addWidget(self.refresh_audio_btn)

        self.transcribe_btn = QPushButton("批量转写")
        self.transcribe_btn.setMinimumHeight(36)
        self.transcribe_btn.clicked.connect(self._start_batch_transcribe)
        tr_btn_row.addWidget(self.transcribe_btn)

        self.transcribe_selected_btn = QPushButton("转写选中")
        self.transcribe_selected_btn.setMinimumHeight(36)
        self.transcribe_selected_btn.clicked.connect(self._start_transcribe_selected)
        tr_btn_row.addWidget(self.transcribe_selected_btn)
        tr_layout.addLayout(tr_btn_row)

        self.tr_progress = QProgressBar()
        tr_layout.addWidget(self.tr_progress)
        self.tr_label = QLabel("")
        tr_layout.addWidget(self.tr_label)
        tr_layout.addStretch()
        tabs.addTab(tr_tab, "转写")

        # ===== Tab 3: 总结 =====
        sm_tab = QWidget()
        sm_layout = QVBoxLayout(sm_tab)

        sf = QFormLayout()
        self.api_key_edit = QLineEdit(self.cfg.get("api_key", ""))
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.setPlaceholderText("sk-...")
        sf.addRow("API Key:", self.api_key_edit)
        self.api_url_edit = QLineEdit(self.cfg.get("api_base_url", "https://api.openai.com/v1"))
        sf.addRow("API地址:", self.api_url_edit)
        self.api_model_edit = QLineEdit(self.cfg.get("api_model", "gpt-4o"))
        sf.addRow("模型:", self.api_model_edit)
        sm_layout.addLayout(sf)

        sm_layout.addWidget(QLabel("转录文件:"))
        self.sm_file_list = QListWidget()
        self.sm_file_list.setMaximumHeight(100)
        sm_layout.addWidget(self.sm_file_list)
        sm_btn_row = QHBoxLayout()
        refresh_sm_btn = QPushButton("刷新")
        refresh_sm_btn.clicked.connect(self._refresh_summary_list)
        sm_btn_row.addWidget(refresh_sm_btn)
        self.merge_cb = QCheckBox("合并所有转录文件一起总结")
        sm_btn_row.addWidget(self.merge_cb)
        sm_btn_row.addStretch()
        sm_layout.addLayout(sm_btn_row)

        self.summarize_btn = QPushButton("开始总结")
        self.summarize_btn.setMinimumHeight(36)
        self.summarize_btn.clicked.connect(self._start_summarize)
        sm_layout.addWidget(self.summarize_btn)
        self.sm_progress = QProgressBar()
        sm_layout.addWidget(self.sm_progress)
        self.sm_label = QLabel("")
        sm_layout.addWidget(self.sm_label)
        sm_layout.addStretch()
        tabs.addTab(sm_tab, "总结")

        # ===== Tab 4: 设置 =====
        st_tab = QWidget()
        st_layout = QVBoxLayout(st_tab)
        sf2 = QFormLayout()
        self.cookie_edit = QLineEdit(self.cfg.get("cookie_file", ""))
        sf2.addRow("Cookie文件:", self.cookie_edit)
        ddr = QHBoxLayout()
        self.download_dir_edit = QLineEdit(self.cfg.get("download_dir", ""))
        ddr.addWidget(self.download_dir_edit)
        ddb = QPushButton("浏览")
        ddb.clicked.connect(lambda: self.download_dir_edit.setText(
            QFileDialog.getExistingDirectory(self, "选择下载目录") or self.download_dir_edit.text()))
        ddr.addWidget(ddb)
        sf2.addRow("下载目录:", ddr)
        adr = QHBoxLayout()
        self.settings_audio_dir_edit = QLineEdit(self.cfg.get("audio_dir", ""))
        adr.addWidget(self.settings_audio_dir_edit)
        adb = QPushButton("浏览")
        adb.clicked.connect(lambda: self.settings_audio_dir_edit.setText(
            QFileDialog.getExistingDirectory(self, "选择音频目录") or self.settings_audio_dir_edit.text()))
        adr.addWidget(adb)
        sf2.addRow("音频目录:", adr)
        tdr = QHBoxLayout()
        self.settings_tr_dir_edit = QLineEdit(self.cfg.get("transcript_dir", ""))
        tdr.addWidget(self.settings_tr_dir_edit)
        tdb = QPushButton("浏览")
        tdb.clicked.connect(lambda: self.settings_tr_dir_edit.setText(
            QFileDialog.getExistingDirectory(self, "选择转写输出目录") or self.settings_tr_dir_edit.text()))
        tdr.addWidget(tdb)
        sf2.addRow("转写输出目录:", tdr)
        self.session_id_edit = QLineEdit(self.cfg.get("session_id", ""))
        sf2.addRow("Session ID:", self.session_id_edit)
        st_layout.addLayout(sf2)
        save_btn = QPushButton("保存设置")
        save_btn.clicked.connect(self._save_settings)
        st_layout.addWidget(save_btn)
        st_layout.addStretch()
        tabs.addTab(st_tab, "设置")

        right_layout.addWidget(tabs)

        # 日志
        lg = QGroupBox("日志")
        ll = QVBoxLayout(lg)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(130)
        ll.addWidget(self.log_text)
        right_layout.addWidget(lg)

        # 分割
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        main_layout.addWidget(splitter)

    # ========================= 数据加载 =========================

    def _load_semesters(self):
        if self.semester_cache.has("all"):
            self._on_semesters_loaded({"semesters": self.semester_cache.get("all")})
            return
        self._log("加载学期列表...")
        self._run_worker("semesters", _on=self._on_semesters_loaded)

    def _on_semesters_loaded(self, data):
        self.semester_cache.set("all", data.get("semesters", []))
        self.sem_combo.clear()
        for s in data.get("semesters", []):
            label = s.get("CNAME", s.get("xqCode", ""))
            if s.get("currentFlag") == 2:
                label += " [当前]"
            self.sem_combo.addItem(label, s.get("xqCode"))
        self._log(f"加载到 {self.sem_combo.count()} 个学期")

    def _on_semester_changed(self, idx):
        xq_code = self.sem_combo.itemData(idx)
        if not xq_code:
            return
        self._log(f"加载课程: {xq_code}")
        self.course_list.clear()
        self.replay_list.clear()
        if self.course_cache.has(xq_code):
            self._on_courses_loaded({"courses": self.course_cache.get(xq_code)}, xq_code)
            return
        self._run_worker(
            "courses",
            xq_code=xq_code,
            _on=lambda data, code=xq_code: self._on_courses_loaded(data, code),
        )

    def _on_courses_loaded(self, data, xq_code=None):
        self.courses = data.get("courses", [])
        if xq_code:
            self.course_cache.set(xq_code, self.courses)
        self.course_list.clear()
        for co in self.courses:
            text = f"{co['name']} | {co['course_num']} | {co.get('teacher_name','')}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, co)
            self.course_list.addItem(item)
        self._log(f"加载到 {len(self.courses)} 门课程")

    def _on_course_selected(self, item):
        self.current_course = item.data(Qt.UserRole)
        co = self.current_course
        self._log(f"选择课程: {co['name']} (cId={co['id']})")
        self.replay_list.clear()
        course_id = co["id"]
        if self.calendar_cache.has(course_id):
            self._on_calendar_loaded(
                {"calendar": self.calendar_cache.get(course_id)}, course_id
            )
            return
        self._run_worker(
            "calendar",
            c_id=course_id,
            _on=lambda data, cid=course_id: self._on_calendar_loaded(data, cid),
        )

    def _on_calendar_loaded(self, data, course_id=None):
        self.calendar = data.get("calendar", [])
        if course_id:
            self.calendar_cache.set(course_id, self.calendar)
        self.replay_list.clear()
        for cal in self.calendar:
            time_str = cal.get("courseBetween", "")
            name = cal.get("courseScheName") or cal.get("content", "")
            if name and len(name) > 60:
                name = name[:60] + "..."
            item = QListWidgetItem(f"{time_str} | {name}")
            item.setData(Qt.UserRole, cal)
            self.replay_list.addItem(item)
        self._log(f"加载到 {len(self.calendar)} 次回放")
        self._mark_downloaded()

    def _on_replay_selection_changed(self):
        count = len(self.replay_list.selectedItems())
        self.replay_count_label.setText(f"已选: {count}")
        enable = count > 0 and self.current_course is not None
        self.dl_btn.setEnabled(enable)
        self.dl_audio_btn.setEnabled(enable)

    # ========================= 批量下载 =========================

    def _get_stream_key(self):
        keys = ["course_url", "teacher_url", "student_url",
                "teacher_closeup_url", "student_closeup_url"]
        return keys[self.stream_combo.currentIndex()]

    def _update_download_button_text(self, *_):
        if self.audio_only_cb.isChecked():
            self.dl_btn.setText("下载选中音频")
        else:
            self.dl_btn.setText("下载选中视频")

    def _start_download_from_options(self):
        self._start_batch_download(audio_only=self.audio_only_cb.isChecked())

    def _start_batch_download(self, audio_only=False):
        selected = self.replay_list.selectedItems()
        if not selected or not self.current_course:
            QMessageBox.warning(self, "提示", "请先选择课程和至少一次回放")
            return

        co = self.current_course
        stream_key = self._get_stream_key()
        stream_label = self.stream_combo.currentText().split(" (")[0]
        safe_name = "".join(c if c.isalnum() or c in "._- " else "_" for c in co["name"])
        save_dir = self.path_edit.text() or self.cfg["download_dir"]
        os.makedirs(save_dir, exist_ok=True)
        self.cfg["download_dir"] = save_dir
        self.download_dir_edit.setText(save_dir)
        save_config(self.cfg)
        ext = "m4a" if audio_only else "mp4"

        items = []
        self.task_tree.clear()
        for item in selected:
            sched = item.data(Qt.UserRole)
            time_str = sched.get("courseBetween", "").replace(":", "").replace(" ", "_")
            filename = f"{safe_name}_{time_str}_{stream_label}.{ext}"
            output_path = os.path.join(save_dir, filename)

            twi = QTreeWidgetItem(["等待", filename, sched.get("courseBetween", "")])
            twi.setData(0, Qt.UserRole, output_path)
            self.task_tree.addTopLevelItem(twi)

            items.append({
                "sched_id": sched["id"],
                "label": time_str,
                "output_path": output_path,
                "audio_only": audio_only,
            })

        self._log(f"开始批量{'音频' if audio_only else '视频'}下载: {len(items)} 个任务")
        self.dl_btn.setEnabled(False)
        self.dl_audio_btn.setEnabled(False)
        self.progress_bar.setValue(0)

        self._run_worker("batch_download",
                         items=items, stream_key=stream_key, user_id="170179",
                         _on=self._on_batch_dl_done,
                         _progress=self._on_progress,
                         _item_start=self._on_item_start,
                         _item_done=self._on_item_done,
                         _item_fail=self._on_item_fail)

    def _on_item_start(self, idx, message):
        if idx < self.task_tree.topLevelItemCount():
            twi = self.task_tree.topLevelItem(idx)
            twi.setText(0, message)

    def _on_item_done(self, idx, path):
        if idx < self.task_tree.topLevelItemCount():
            twi = self.task_tree.topLevelItem(idx)
            twi.setText(0, "完成")
            twi.setForeground(0, QFont("", -1, -1, QFont.Bold).weight if False else Qt.darkGreen)
            twi.setTextColor(0, Qt.darkGreen)
        self._log(f"  [{idx+1}] 完成: {os.path.basename(path)}")

    def _on_item_fail(self, idx, reason):
        if idx < self.task_tree.topLevelItemCount():
            twi = self.task_tree.topLevelItem(idx)
            twi.setText(0, "失败")
            twi.setTextColor(0, Qt.red)
            twi.setText(2, reason)
        self._log(f"  [{idx+1}] 失败: {reason}")

    def _on_batch_dl_done(self, data):
        self._log("批量下载结束")
        self.dl_btn.setEnabled(True)
        self.dl_audio_btn.setEnabled(True)
        self._mark_downloaded()
        self._refresh_audio_list()
        if data.get("audio_only") and self.tr_file_list.count() > 0:
            self._log("音频已加入转写列表")
            self.tabs.setCurrentIndex(1)

    def _mark_downloaded(self):
        """扫描下载目录，在回放列表中标记已下载的项"""
        if not self.current_course:
            return
        co = self.current_course
        safe_name = "".join(c if c.isalnum() or c in "._- " else "_" for c in co["name"])
        save_dir = self.path_edit.text() or self.cfg["download_dir"]

        # 收集下载目录中的所有文件
        existing_files = set()
        if os.path.exists(save_dir):
            for f in os.listdir(save_dir):
                if f.startswith(safe_name):
                    existing_files.add(f)

        # 标记每条回放
        for i in range(self.replay_list.count()):
            item = self.replay_list.item(i)
            sched = item.data(Qt.UserRole)
            time_str = sched.get("courseBetween", "").replace(":", "").replace(" ", "_")
            current_text = item.text()

            # 去掉旧的标记前缀
            for prefix in ("✓ ", "○ "):
                if current_text.startswith(prefix):
                    current_text = current_text[2:]
                    break

            # 检查是否存在匹配的文件
            downloaded = any(time_str in f for f in existing_files)
            if downloaded:
                item.setText(f"✓ {current_text}")
                item.setForeground(Qt.darkGreen)
            else:
                item.setText(f"○ {current_text}")
                item.setForeground(Qt.black)

    # ========================= 转写 =========================

    def _on_device_changed(self, device):
        self.cfg["whisper_device"] = device

    def _browse_audio_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择音频所在目录")
        if path:
            self.audio_dir_edit.setText(path)
            self.cfg["audio_dir"] = path
            save_config(self.cfg)
            self._refresh_audio_list()

    def _browse_transcript_out_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择转写输出目录")
        if path:
            self.tr_out_dir_edit.setText(path)
            self.cfg["transcript_dir"] = path
            save_config(self.cfg)

    def _refresh_audio_list(self):
        self.tr_file_list.clear()
        # 从音频目录收集
        audio_dir = self.audio_dir_edit.text()
        dirs_to_scan = []
        if audio_dir and os.path.exists(audio_dir):
            dirs_to_scan.append(audio_dir)
        # 也从下载目录收集
        dl_dir = self.path_edit.text() or self.cfg["download_dir"]
        if dl_dir and os.path.exists(dl_dir) and dl_dir not in dirs_to_scan:
            dirs_to_scan.append(dl_dir)

        seen = set()
        for d in dirs_to_scan:
            for root, _, files in os.walk(d):
                for f in files:
                    if f.lower().endswith((".mp3", ".wav", ".m4a", ".flac", ".aac")):
                        full = os.path.join(root, f)
                        if full not in seen:
                            seen.add(full)
                            item = QListWidgetItem(f)
                            item.setData(Qt.UserRole, full)
                            self.tr_file_list.addItem(item)

        self._log(f"扫描到 {self.tr_file_list.count()} 个音频文件")
        if self.tr_file_list.count() > 0:
            self.tr_file_list.setCurrentRow(0)

    def _get_transcribe_files(self):
        """获取待转写的文件列表"""
        if self.tr_file_list.count() == 0:
            self._refresh_audio_list()
        return [self.tr_file_list.item(i).data(Qt.UserRole)
                for i in range(self.tr_file_list.count())]

    def _start_batch_transcribe(self):
        files = self._get_transcribe_files()
        if not files:
            QMessageBox.warning(self, "提示", "没有找到音频文件，请先下载音频或选择目录")
            return
        self._do_transcribe(files)

    def _start_transcribe_selected(self):
        selected = self.tr_file_list.selectedItems()
        if not selected:
            QMessageBox.warning(self, "提示", "请在文件列表中选中要转写的文件")
            return
        files = [it.data(Qt.UserRole) for it in selected]
        self._do_transcribe(files)

    def _do_transcribe(self, files):
        # 持久化当前设置
        self.cfg["whisper_device"] = self.device_combo.currentText()
        self.cfg["whisper_model"] = self.model_combo.currentText()
        self.cfg["whisper_language"] = self.lang_combo.currentText()
        self.cfg["transcript_dir"] = self.tr_out_dir_edit.text()
        save_config(self.cfg)
        cfg = load_config()
        out_dir = self.tr_out_dir_edit.text() or cfg.get("transcript_dir", "")
        os.makedirs(out_dir, exist_ok=True)

        self._log(f"开始批量转写: {len(files)} 个文件")
        self.transcribe_btn.setEnabled(False)
        self.transcribe_selected_btn.setEnabled(False)
        self.tr_progress.setValue(0)

        self._run_worker("batch_transcribe",
                         files=files, model_size=self.model_combo.currentText(),
                         out_dir=out_dir,
                         _on=self._on_batch_tr_done,
                         _progress=self._on_tr_progress,
                         _item_done=self._on_tr_item_done,
                         _item_fail=self._on_tr_item_fail)

    def _on_tr_progress(self, value, msg):
        self.tr_progress.setValue(min(value, 100))
        self.tr_label.setText(msg)

    def _on_tr_item_done(self, idx, path):
        self._log(f"  [{idx+1}] 转写完成: {os.path.basename(path)}")

    def _on_tr_item_fail(self, idx, reason):
        self._log(f"  [{idx+1}] 转写失败: {reason}")

    def _on_batch_tr_done(self, data):
        self._log("批量转写结束")
        self.tr_progress.setValue(100)
        self.tr_label.setText("转写完成")
        self.transcribe_btn.setEnabled(True)
        self.transcribe_selected_btn.setEnabled(True)
        self._refresh_summary_list()
        if self.sm_file_list.count() > 0:
            self.tabs.setCurrentIndex(2)

    # ========================= 总结 =========================

    def _refresh_summary_list(self):
        self.sm_file_list.clear()
        cfg = load_config()
        tr_dir = cfg.get("transcript_dir",
                         os.path.join(os.path.dirname(__file__), "transcripts"))
        if os.path.exists(tr_dir):
            for f in sorted(os.listdir(tr_dir)):
                if f.endswith("_transcript.json"):
                    item = QListWidgetItem(f)
                    item.setData(Qt.UserRole, os.path.join(tr_dir, f))
                    self.sm_file_list.addItem(item)
        self._log(f"扫描到 {self.sm_file_list.count()} 个转录文件")
        if self.sm_file_list.count() > 0:
            self.sm_file_list.setCurrentRow(self.sm_file_list.count() - 1)

    def _start_summarize(self):
        # 更新 API 配置
        self.cfg["api_key"] = self.api_key_edit.text()
        self.cfg["api_base_url"] = self.api_url_edit.text()
        self.cfg["api_model"] = self.api_model_edit.text()
        save_config(self.cfg)

        merge = self.merge_cb.isChecked()
        if merge:
            # 合并所有
            texts = []
            for i in range(self.sm_file_list.count()):
                path = self.sm_file_list.item(i).data(Qt.UserRole)
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    texts.append(data.get("full_text", ""))
            if not texts:
                QMessageBox.warning(self, "提示", "没有可用的转录文件")
                return
            text = "\n\n---\n\n".join(texts)
            self._log(f"合并 {len(texts)} 个转录文件，总长度: {len(text)} 字符")
        else:
            selected = self.sm_file_list.selectedItems()
            if not selected:
                QMessageBox.warning(self, "提示", "请选中一个转录文件，或勾选'合并所有'")
                return
            path = selected[0].data(Qt.UserRole)
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            text = data.get("full_text", "")
            segs = data.get("segments", [])
            if not text:
                text = "".join(s.get("text", "") for s in segs)

        if not text.strip():
            QMessageBox.warning(self, "提示", "转写文本为空")
            return

        self._log(f"开始总结，文本长度: {len(text)} 字符")
        self.summarize_btn.setEnabled(False)
        self.sm_progress.setValue(0)

        cfg = load_config()
        out_dir = cfg.get("summary_dir",
                          os.path.join(os.path.dirname(__file__), "summaries"))
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir,
                                f"summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md")

        self._run_worker("summarize", text=text, output_path=out_path,
                         _on=self._on_summarize_done,
                         _progress=self._on_sm_progress)

    def _on_sm_progress(self, value, msg):
        self.sm_progress.setValue(min(value, 100))
        self.sm_label.setText(msg)

    def _on_summarize_done(self, data):
        summary = data.get("summary", "")
        out_path = data.get("output_path", "")
        self._log(f"总结完成: {out_path}")
        self.sm_progress.setValue(100)
        self.sm_label.setText("总结完成")
        self.summarize_btn.setEnabled(True)
        QMessageBox.information(self, "完成",
                                f"总结完成:\n{out_path}\n\n"
                                f"预览:\n{summary[:300]}...")

    # ========================= 通用方法 =========================

    def _run_worker(self, task, _on=None, _progress=None, _error=None,
                    _item_start=None, _item_done=None, _item_fail=None,
                    **kwargs):
        self.worker = CrawlerWorker(task, **kwargs)
        if _on:
            self.worker.signals.finished.connect(_on)
        if _progress:
            self.worker.signals.progress.connect(_progress)
        if _item_start:
            self.worker.signals.item_start.connect(_item_start)
        if _item_done:
            self.worker.signals.item_done.connect(_item_done)
        if _item_fail:
            self.worker.signals.item_fail.connect(_item_fail)
        self.worker.signals.error.connect(_error or self._on_error)
        self.worker.signals.log.connect(self._log)
        self.worker.start()

    def _on_progress(self, value, msg):
        self.progress_bar.setValue(min(value, 100))
        self.progress_label.setText(msg)

    def _on_error(self, msg):
        self._log(f"错误: {msg}")
        QMessageBox.critical(self, "错误", msg)
        self.dl_btn.setEnabled(True)
        self.dl_audio_btn.setEnabled(True)
        self.transcribe_btn.setEnabled(True)
        self.transcribe_selected_btn.setEnabled(True)
        self.summarize_btn.setEnabled(True)

    def _log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{ts}] {msg}")

    def _save_settings(self):
        self.cfg["cookie_file"] = self.cookie_edit.text()
        self.cfg["download_dir"] = self.download_dir_edit.text()
        self.cfg["audio_dir"] = self.settings_audio_dir_edit.text()
        self.cfg["transcript_dir"] = self.settings_tr_dir_edit.text()
        self.cfg["session_id"] = self.session_id_edit.text()
        self.cfg["api_key"] = self.api_key_edit.text()
        self.cfg["api_base_url"] = self.api_url_edit.text()
        self.cfg["api_model"] = self.api_model_edit.text()
        self.cfg["whisper_model"] = self.model_combo.currentText()
        self.cfg["whisper_language"] = self.lang_combo.currentText()
        self.cfg["whisper_device"] = self.device_combo.currentText()
        save_config(self.cfg)
        # 同步到转写 tab 的编辑框
        self.path_edit.setText(self.cfg["download_dir"])
        self.audio_dir_edit.setText(self.cfg["audio_dir"])
        self.tr_out_dir_edit.setText(self.cfg["transcript_dir"])
        self._log("设置已保存")
        QMessageBox.information(self, "设置", "设置已保存")


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei", 10))
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
