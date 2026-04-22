import ctypes
import queue
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk


class SettingsDialog(tk.Toplevel):
    """配置对话框：允许用户填写 ASR / LLM / 触发词等参数。"""

    def __init__(self, parent, config, on_save):
        super().__init__(parent)
        self.title("设置")
        self.geometry("700x620")
        self.resizable(False, False)
        self.config = config
        self.on_save = on_save
        self._build_ui()
        self._load_values()
        self.transient(parent)
        self.grab_set()

    def _build_ui(self):
        pad = {"padx": 10, "pady": 5}

        # ---------- ASR 提供商选择 ----------
        frm_provider = tk.Frame(self)
        frm_provider.pack(fill="x", **pad)
        tk.Label(frm_provider, text="ASR 提供商:").pack(side="left")
        self.cmb_provider = ttk.Combobox(
            frm_provider,
            values=["xunfei", "http_asr"],
            state="readonly",
            width=20,
        )
        self.cmb_provider.pack(side="left", padx=(5, 0))
        self.cmb_provider.bind("<<ComboboxSelected>>", self._on_provider_change)
        tk.Label(
            frm_provider,
            text="讯飞=流式低延迟 | http_asr=内置转写客户端(兼容 /audio/transcriptions)",
            fg="#666666",
            font=("Microsoft YaHei", 9),
        ).pack(side="left", padx=(10, 0))

        # ---------- 讯飞 ASR ----------
        self.frm_xunfei = tk.LabelFrame(self, text="讯飞语音听写 (xunfei)")
        self.frm_xunfei.pack(fill="x", **pad)
        tk.Label(self.frm_xunfei, text="APPID:").grid(
            row=0, column=0, sticky="e", **pad
        )
        self.entry_app_id = tk.Entry(self.frm_xunfei, width=40)
        self.entry_app_id.grid(row=0, column=1, **pad)
        tk.Label(self.frm_xunfei, text="APIKey:").grid(
            row=1, column=0, sticky="e", **pad
        )
        self.entry_api_key = tk.Entry(self.frm_xunfei, width=40)
        self.entry_api_key.grid(row=1, column=1, **pad)
        tk.Label(self.frm_xunfei, text="APISecret:").grid(
            row=2, column=0, sticky="e", **pad
        )
        self.entry_api_secret = tk.Entry(self.frm_xunfei, width=40, show="*")
        self.entry_api_secret.grid(row=2, column=1, **pad)

        # ---------- HTTP ASR ----------
        self.frm_http = tk.LabelFrame(self, text="兼容音频转写 API (http_asr)")
        self.frm_http.pack(fill="x", **pad)
        tk.Label(self.frm_http, text="API Base:").grid(
            row=0, column=0, sticky="e", **pad
        )
        self.entry_asr_base = tk.Entry(self.frm_http, width=40)
        self.entry_asr_base.grid(row=0, column=1, **pad)
        tk.Label(self.frm_http, text="API Key:").grid(
            row=1, column=0, sticky="e", **pad
        )
        self.entry_asr_key = tk.Entry(self.frm_http, width=40, show="*")
        self.entry_asr_key.grid(row=1, column=1, **pad)
        tk.Label(
            self.frm_http,
            text="可直连支持 /audio/transcriptions 的云端 API；若服务未鉴权可留空",
            fg="#666666",
            font=("Microsoft YaHei", 9),
            wraplength=420,
            justify="left",
        ).grid(row=2, column=1, sticky="w", padx=10, pady=(0, 5))
        tk.Label(self.frm_http, text="Model:").grid(row=2, column=0, sticky="e", **pad)
        self.entry_asr_model = tk.Entry(self.frm_http, width=40)
        self.entry_asr_model.grid(row=3, column=1, **pad)
        tk.Label(self.frm_http, text="Language:").grid(
            row=4, column=0, sticky="e", **pad
        )
        self.entry_asr_lang = tk.Entry(self.frm_http, width=40)
        self.entry_asr_lang.grid(row=4, column=1, **pad)
        tk.Label(self.frm_http, text="分段时长(ms):").grid(
            row=5, column=0, sticky="e", **pad
        )
        self.entry_asr_seg = tk.Entry(self.frm_http, width=40)
        self.entry_asr_seg.grid(row=5, column=1, **pad)

        # ---------- LLM ----------
        frm_llm = tk.LabelFrame(self, text="大语言模型 (LLM)")
        frm_llm.pack(fill="x", **pad)
        tk.Label(frm_llm, text="API Base:").grid(row=0, column=0, sticky="e", **pad)
        self.entry_api_base = tk.Entry(frm_llm, width=40)
        self.entry_api_base.grid(row=0, column=1, **pad)
        tk.Label(frm_llm, text="API Key:").grid(row=1, column=0, sticky="e", **pad)
        self.entry_llm_key = tk.Entry(frm_llm, width=40, show="*")
        self.entry_llm_key.grid(row=1, column=1, **pad)
        tk.Label(frm_llm, text="Model:").grid(row=2, column=0, sticky="e", **pad)
        self.entry_model = tk.Entry(frm_llm, width=40)
        self.entry_model.grid(row=2, column=1, **pad)

        # ---------- 触发词 ----------
        frm_trig = tk.LabelFrame(self, text="提问触发词（每行一个）")
        frm_trig.pack(fill="both", expand=True, **pad)
        self.txt_triggers = tk.Text(frm_trig, height=6, wrap="word")
        self.txt_triggers.pack(fill="both", expand=True, padx=5, pady=5)

        # ---------- 按钮 ----------
        frm_btn = tk.Frame(self)
        frm_btn.pack(fill="x", **pad)
        tk.Button(frm_btn, text="保存", command=self._save, width=10).pack(
            side="right", padx=5
        )
        tk.Button(frm_btn, text="取消", command=self.destroy, width=10).pack(
            side="right", padx=5
        )

    def _on_provider_change(self, event=None):
        provider = self.cmb_provider.get()
        if provider == "xunfei":
            self.frm_xunfei.pack(
                fill="x", padx=10, pady=5, after=self.cmb_provider.master
            )
            self.frm_http.pack_forget()
        else:
            self.frm_http.pack(
                fill="x", padx=10, pady=5, after=self.cmb_provider.master
            )
            self.frm_xunfei.pack_forget()
        self._adjust_size_to_content()

    def _adjust_size_to_content(self):
        self.update_idletasks()
        required_width = max(700, self.winfo_reqwidth() + 20)
        required_height = min(
            max(620, self.winfo_reqheight() + 20), self.winfo_screenheight() - 80
        )
        self.geometry(f"{required_width}x{required_height}")

    def _load_values(self):
        provider = self.config.get("asr.provider", "xunfei")
        self.cmb_provider.set(provider)

        self.entry_app_id.insert(0, self.config.get("asr.app_id", ""))
        self.entry_api_key.insert(0, self.config.get("asr.api_key", ""))
        self.entry_api_secret.insert(0, self.config.get("asr.api_secret", ""))

        self.entry_asr_base.insert(
            0, self.config.get("asr.api_base", "https://api.openai.com/v1")
        )
        self.entry_asr_key.insert(0, self.config.get("asr.api_key", ""))
        self.entry_asr_model.insert(0, self.config.get("asr.model", "whisper-1"))
        self.entry_asr_lang.insert(0, self.config.get("asr.language", "zh"))
        self.entry_asr_seg.insert(
            0, str(self.config.get("asr.segment_duration_ms", 1500))
        )

        self.entry_api_base.insert(
            0, self.config.get("llm.api_base", "https://api.openai.com/v1")
        )
        self.entry_llm_key.insert(0, self.config.get("llm.api_key", ""))
        self.entry_model.insert(0, self.config.get("llm.model", "gpt-4o-mini"))
        triggers = self.config.get("detector.triggers", [])
        self.txt_triggers.insert("1.0", "\n".join(triggers))
        self._on_provider_change()

    def _save(self):
        triggers_raw = self.txt_triggers.get("1.0", "end").strip()
        triggers = [t.strip() for t in triggers_raw.splitlines() if t.strip()]
        provider = self.cmb_provider.get()

        new_config = {
            "asr": {
                "provider": provider,
                "app_id": self.entry_app_id.get().strip(),
                "api_key": self.entry_api_key.get().strip()
                if provider == "xunfei"
                else self.entry_asr_key.get().strip(),
                "api_secret": self.entry_api_secret.get().strip(),
                "api_base": self.entry_asr_base.get().strip(),
                "model": self.entry_asr_model.get().strip(),
                "language": self.entry_asr_lang.get().strip(),
                "segment_duration_ms": int(self.entry_asr_seg.get().strip() or 1500),
            },
            "llm": {
                "api_base": self.entry_api_base.get().strip(),
                "api_key": self.entry_llm_key.get().strip(),
                "model": self.entry_model.get().strip(),
            },
            "detector": {
                "triggers": triggers,
            },
        }
        self.on_save(new_config)
        self.destroy()


def _play_system_alert():
    """播放系统提示音（跨平台兼容）。"""
    try:
        if ctypes.windll:
            ctypes.windll.MessageBeep(0x30)
            return
    except Exception:
        pass
    try:
        import winsound

        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    except Exception:
        pass


class MainWindow:
    """tkinter 主界面。"""

    def __init__(self, on_start, on_stop, on_settings, on_finish_question=None):
        self.on_start = on_start
        self.on_stop = on_stop
        self.on_settings = on_settings
        self.on_finish_question = on_finish_question

        self.root = tk.Tk()
        self.root.title("AI课堂助手")
        self.root.geometry("900x600")
        self.root.minsize(700, 450)

        self._running = False
        self._highlighting = False
        self._current_trigger = None
        self._build_ui()
        self._poll_ui_queue()

    # ------------------------------------------------------------------ #
    # UI 构建
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        # 顶部工具栏
        toolbar = tk.Frame(self.root)
        toolbar.pack(fill="x", padx=10, pady=8)

        tk.Label(toolbar, text="AI课堂助手", font=("Microsoft YaHei", 14, "bold")).pack(
            side="left"
        )

        self.btn_settings = tk.Button(
            toolbar, text="设置", command=self.on_settings, width=8
        )
        self.btn_settings.pack(side="right", padx=5)

        # 结束提问按钮（默认禁用，触发后启用）
        self.btn_finish = tk.Button(
            toolbar,
            text="结束提问",
            command=self._on_finish,
            width=10,
            bg="#FF9800",
            fg="white",
            font=("Microsoft YaHei", 10, "bold"),
            state="disabled",
        )
        self.btn_finish.pack(side="right", padx=5)

        self.btn_toggle = tk.Button(
            toolbar,
            text="开始听课",
            command=self._toggle,
            width=10,
            bg="#4CAF50",
            fg="white",
        )
        self.btn_toggle.pack(side="right", padx=5)

        # 中间分栏
        paned = tk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill="both", expand=True, padx=10, pady=5)

        # 左侧：实时字幕
        left_frame = tk.LabelFrame(paned, text="实时字幕")
        paned.add(left_frame, minsize=300)
        self.subtitle_box = scrolledtext.ScrolledText(
            left_frame, wrap="word", state="disabled", font=("Microsoft YaHei", 11)
        )
        self.subtitle_box.pack(fill="both", expand=True, padx=5, pady=5)
        self.subtitle_box.tag_config("teacher", foreground="#333333")
        self.subtitle_box.tag_config(
            "highlight", foreground="red", font=("Microsoft YaHei", 11, "bold")
        )

        # 右侧：AI 回答
        right_frame = tk.LabelFrame(paned, text="AI 回答")
        paned.add(right_frame, minsize=300)
        self.answer_box = scrolledtext.ScrolledText(
            right_frame, wrap="word", state="disabled", font=("Microsoft YaHei", 11)
        )
        self.answer_box.pack(fill="both", expand=True, padx=5, pady=5)
        self.answer_box.tag_config("answer", foreground="#1565C0")
        self.answer_box.tag_config(
            "meta", foreground="#999999", font=("Microsoft YaHei", 9)
        )

        # 底部状态栏
        self.status_var = tk.StringVar(value="就绪")
        status_bar = tk.Label(
            self.root, textvariable=self.status_var, bd=1, relief=tk.SUNKEN, anchor=tk.W
        )
        status_bar.pack(fill="x", padx=10, pady=(0, 8))

        # 线程安全队列（由外部 AppController 注入）
        self.ui_queue: queue.Queue = queue.Queue()

    # ------------------------------------------------------------------ #
    # 交互控制
    # ------------------------------------------------------------------ #
    def _toggle(self):
        if not self._running:
            self.on_start()
        else:
            self.on_stop()

    def _on_finish(self):
        """用户按下「结束提问」按钮。"""
        if self.on_finish_question:
            self.on_finish_question()

    def set_running(self, running: bool):
        self._running = running
        if running:
            self.btn_toggle.config(text="停止", bg="#f44336")
            self.set_status("运行中")
        else:
            self.btn_toggle.config(text="开始听课", bg="#4CAF50")
            self.btn_finish.config(state="disabled")
            self._highlighting = False
            self._current_trigger = None
            self.set_status("已停止")

    def set_status(self, text: str):
        self.status_var.set(text)

    # ------------------------------------------------------------------ #
    # 内容更新（供外部调用）
    # ------------------------------------------------------------------ #
    def append_subtitle(self, text: str):
        """将 ASR 最新完整文本追加到字幕区，自动处理流式修正与换句。"""
        if not hasattr(self, "_subtitle_last"):
            self._subtitle_last = ""

        if text == self._subtitle_last:
            return

        box = self.subtitle_box
        box.config(state="normal")

        # 收集阶段：新追加的文本标红
        tag = ("highlight", "teacher") if self._highlighting else ("teacher",)

        # 1) 最常见：纯追加
        if text.startswith(self._subtitle_last):
            append_text = text[len(self._subtitle_last) :]
            box.insert("end", append_text, tag)
            self._subtitle_last = text
        else:
            # 2) 文本显著变短 → 大概率 vad_eos 触发新句子
            if self._subtitle_last and len(text) < len(self._subtitle_last) * 0.3:
                box.insert("end", "\n" + text, tag)
                self._subtitle_last = text
            else:
                # 3) 修正：尝试删除旧差异并重写
                content = box.get("1.0", "end-1c")
                common = 0
                min_len = min(len(self._subtitle_last), len(text))
                for i in range(min_len):
                    if self._subtitle_last[i] == text[i]:
                        common += 1
                    else:
                        break
                old_tail = len(self._subtitle_last) - common
                if old_tail > 0 and content.endswith(self._subtitle_last):
                    box.delete(f"end-{old_tail}c", "end-1c")
                    box.insert("end", text[common:], tag)
                else:
                    # 兜底：加空格追加（极少发生）
                    box.insert("end", " " + text, tag)
                self._subtitle_last = text

        box.see("end")
        box.config(state="disabled")

    def _apply_highlight_existing(self, trigger: str):
        """将字幕区中已有文本里从触发词到行尾的内容标红。"""
        box = self.subtitle_box
        box.config(state="normal")

        content = box.get("1.0", "end-1c")
        idx = content.rfind(trigger)
        if idx < 0:
            box.config(state="disabled")
            return

        # 计算 tk Text 索引：offset+1 因为 tk Text 索引从 1 开始
        line_start = content[:idx].count("\n") + 1
        col_start = idx - content[:idx].rfind("\n") - 1
        start_index = f"{line_start}.{col_start}"

        box.tag_add("highlight", start_index, "end-1c")
        box.config(state="disabled")

    def append_ai_answer(self, text: str, is_new: bool = False):
        if is_new:
            import time

            ts = time.strftime("%H:%M:%S")
            self._insert_text(self.answer_box, f"\n[{ts}] ", tag="meta")
        if text:
            self._insert_text(self.answer_box, text, tag="answer")

    def _insert_text(self, widget: scrolledtext.ScrolledText, text: str, tag: str = ""):
        widget.config(state="normal")
        widget.insert("end", text, tag)
        widget.see("end")
        widget.config(state="disabled")

    # ------------------------------------------------------------------ #
    # 跨线程队列轮询
    # ------------------------------------------------------------------ #
    def _poll_ui_queue(self):
        try:
            while True:
                msg = self.ui_queue.get_nowait()
                self._handle_msg(msg)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_ui_queue)

    def _handle_msg(self, msg: dict):
        mtype = msg.get("type")
        if mtype == "asr_text":
            self.append_subtitle(msg.get("content", ""))
        elif mtype == "question_detected":
            trigger = msg.get("trigger", "")
            self._highlighting = True
            self._current_trigger = trigger
            self.btn_finish.config(state="normal")
            self.status_var.set(f"检测到提问「{trigger}」，请按「结束提问」发送给 AI")
            if trigger:
                self._apply_highlight_existing(trigger)
            _play_system_alert()
        elif mtype == "question_sent":
            self._highlighting = False
            self._current_trigger = None
            self.btn_finish.config(state="disabled")
            self.set_status("已发送提问给 AI，等待回答...")
        elif mtype == "answer_start":
            self.append_ai_answer("", is_new=True)
        elif mtype == "answer_token":
            self.append_ai_answer(msg.get("content", ""), is_new=False)
        elif mtype == "answer_end":
            self.append_ai_answer("\n", is_new=False)
        elif mtype == "status":
            self.set_status(msg.get("content", ""))
        elif mtype == "error":
            self.set_status(f"错误: {msg.get('message', '')}")
            messagebox.showerror("错误", msg.get("message", "未知错误"))
            self.set_running(False)

    # ------------------------------------------------------------------ #
    # 主循环入口
    # ------------------------------------------------------------------ #
    def run(self):
        self.root.mainloop()
