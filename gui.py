import os
import json
import shutil
import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, simpledialog
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from node_manager import NodeManager, Node
import sys
import queue
import subprocess
import ctypes

# Config File
CONFIG_FILE = "config.json"

class TextRedirector(object):
    def __init__(self, queue):
        self.queue = queue

    def write(self, str):
        self.queue.put(str)

    def flush(self):
        pass

class App(ttk.Window):
    def __init__(self):
        super().__init__(themename="darkly")
        self.title("ComfyNode Sync - ComfyUI 节点管理与迁移")
        self.geometry("1200x850")

        # Configure Treeview Style for larger checkboxes and easier clicking
        style = ttk.Style()
        style.configure("Treeview", font=('Microsoft YaHei', 12), rowheight=35)
        style.configure("Treeview.Heading", font=('Microsoft YaHei', 12, 'bold'))
        
        # Set selection color to Light Blue (Bootstrap Info color) with Black text for contrast
        style.map("Treeview",
                  background=[('selected', '#5bc0de')],
                  foreground=[('selected', '#000000')])
        
        self.manager = NodeManager()
        self.current_nodes = []
        self.migration_nodes = []
        self.manage_checked = set()
        self.migrate_checked = set()
        
        # Logging Queue
        self.log_queue = queue.Queue()
        
        # UI Variables
        self.comfy_root_var = tk.StringVar()
        self.custom_nodes_path_var = tk.StringVar()
        self.python_path_var = tk.StringVar()
        self.proxy_var = tk.StringVar()
        
        self.old_nodes_path_var = tk.StringVar()
        self.symlink_source_var = tk.StringVar()
        self.workflow_source_var = tk.StringVar()
        self.symlink_target_var = tk.StringVar()
        self.model_target_var = tk.StringVar()
        self.workflow_target_var = tk.StringVar()
        
        # Filter Variables
        self.migrate_filter_var = tk.StringVar()
        self.manage_filter_name_var = tk.StringVar()
        self.manage_filter_type_var = tk.StringVar(value="全部")
        self.manage_filter_status_var = tk.StringVar(value="全部")
        self.migrate_filter_status_var = tk.StringVar(value="全部")
        
        self.manage_filter_name_var.trace("w", lambda *args: self.update_manage_list())
        self.manage_filter_type_var.trace("w", lambda *args: self.update_manage_list())
        self.manage_filter_status_var.trace("w", lambda *args: self.update_manage_list())
        self.migrate_filter_var.trace("w", lambda *args: self.filter_migrate_list())
        self.migrate_filter_status_var.trace("w", lambda *args: self.filter_migrate_list())
        
        self.node_status_map = {} # Cache for node status
        
        self.load_config()
        self.create_widgets()
        
        # Auto-scan if path is set
        if self.comfy_root_var.get():
             self.after(500, self.refresh_current_nodes)
             
        # Start log polling
        self.after(100, self.poll_log_queue)

    def poll_log_queue(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log_text.configure(state='normal')
                self.log_text.insert('end', msg)
                self.log_text.see('end')
                self.log_text.configure(state='disabled')
                self.log_queue.task_done()
        except queue.Empty:
            pass
        finally:
            self.after(100, self.poll_log_queue)

    def get_proxy_url(self):
        port = self.proxy_var.get().strip()
        if not port:
            return None
        # If user entered a full URL, use it
        if port.startswith("http"):
            return port
        # Assume it's just a port
        return f"http://127.0.0.1:{port}"

    def test_proxy(self):
        url = self.get_proxy_url()
        if not url:
            self.log("Please enter a proxy port first.")
            return
            
        def _test():
            import urllib.request
            self.log(f"Testing proxy connection: {url}...")
            
            proxy_handler = urllib.request.ProxyHandler({'http': url, 'https': url})
            opener = urllib.request.build_opener(proxy_handler)
            
            try:
                # Try connecting to a reliable site
                response = opener.open("https://www.google.com", timeout=5)
                if response.status == 200:
                    self.log("Proxy connection successful! (Connected to Google)")
                    messagebox.showinfo("Success", "Proxy connection successful!")
                else:
                    self.log(f"Proxy test returned status code: {response.status}")
            except Exception as e:
                self.log(f"Proxy connection failed: {e}")
                messagebox.showerror("Error", f"Proxy connection failed:\n{e}")

        threading.Thread(target=_test, daemon=True).start()

    def on_closing(self):
        self.save_config()
        self.destroy()

    def create_widgets(self):
        # --- Main Section: PanedWindow (Split Left/Right) ---
        self.main_paned = ttk.Panedwindow(self, orient=HORIZONTAL)
        self.main_paned.pack(fill=BOTH, expand=True, padx=10, pady=5)

        # --- Left Pane: Settings & Tabs ---
        left_frame = ttk.Frame(self.main_paned)
        self.main_paned.add(left_frame, weight=3)

        # --- Top Section: Global Settings (Current Environment) ---
        settings_frame = ttk.Labelframe(left_frame, text="当前环境设置", padding=10)
        settings_frame.pack(fill=X, padx=0, pady=5)
        
        # Row 1: ComfyUI Root
        ttk.Label(settings_frame, text="ComfyUI 根目录:").grid(row=0, column=0, sticky=W, padx=5)
        ttk.Entry(settings_frame, textvariable=self.comfy_root_var).grid(row=0, column=1, sticky=EW, padx=5)
        ttk.Button(settings_frame, text="浏览", command=self.browse_comfy_root, bootstyle="outline").grid(row=0, column=2, padx=5)
        
        # Row 2: Python Path (Auto-detected but editable)
        ttk.Label(settings_frame, text="Python 解释器:").grid(row=1, column=0, sticky=W, padx=5)
        ttk.Entry(settings_frame, textvariable=self.python_path_var).grid(row=1, column=1, sticky=EW, padx=5)
        ttk.Button(settings_frame, text="浏览", command=self.browse_python, bootstyle="outline").grid(row=1, column=2, padx=5)

        # Row 3: Proxy
        ttk.Label(settings_frame, text="代理端口:").grid(row=2, column=0, sticky=W, padx=5)
        
        proxy_frame = ttk.Frame(settings_frame)
        proxy_frame.grid(row=2, column=1, sticky=EW, padx=5)
        
        ttk.Entry(proxy_frame, textvariable=self.proxy_var).pack(side=LEFT, fill=X, expand=True)
        ttk.Button(proxy_frame, text="测试", command=self.test_proxy, bootstyle="info-outline").pack(side=LEFT, padx=5)
        
        ttk.Button(settings_frame, text="保存配置", command=self.save_config, bootstyle="success").grid(row=2, column=2, padx=5)
        
        # Toggle Log Button
        self.log_btn = ttk.Button(settings_frame, text="隐藏日志", command=self.toggle_log_sidebar, bootstyle="secondary-outline")
        self.log_btn.grid(row=0, column=3, rowspan=3, padx=5, sticky=NS)
        
        settings_frame.columnconfigure(1, weight=1)

        # --- Tabs ---
        self.notebook = ttk.Notebook(left_frame)
        self.notebook.pack(fill=BOTH, expand=True, padx=0, pady=5)
        
        # Tab 1: Manage (Management)
        self.tab_manage = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.tab_manage, text="节点管理")
        self.setup_manage_tab()
        
        # Tab 2: Migrate (Advanced)
        self.tab_migrate = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.tab_migrate, text="节点迁移")
        self.setup_migrate_tab()

        # Tab 3: Symlink (Models & Workflows)
        self.tab_symlink = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.tab_symlink, text="资源共享")
        self.setup_symlink_tab()

        # --- Right Pane: Log Section ---
        self.log_frame = ttk.Labelframe(self.main_paned, text="系统日志", padding=10)
        self.main_paned.add(self.log_frame, weight=1)
        
        self.log_text = tk.Text(self.log_frame, state='disabled', width=40, bg='#2b2b2b', fg='#ffffff', font=("Consolas", 9))
        self.log_text.pack(fill=BOTH, expand=True)
        
        sys.stdout = TextRedirector(self.log_queue)
        sys.stderr = TextRedirector(self.log_queue)

    def toggle_log_sidebar(self):
        if str(self.log_frame) in self.main_paned.panes():
            self.main_paned.forget(self.log_frame)
            self.log_btn.configure(text="显示日志")
        else:
            self.main_paned.add(self.log_frame, weight=1)
            self.log_btn.configure(text="隐藏日志")

    def setup_manage_tab(self):
        # Filter & Selection Bar
        filter_frame = ttk.Frame(self.tab_manage)
        filter_frame.pack(fill=X, pady=5)
        
        ttk.Label(filter_frame, text="名称:").pack(side=LEFT, padx=2)
        ttk.Entry(filter_frame, textvariable=self.manage_filter_name_var, width=15).pack(side=LEFT, padx=5)

        ttk.Label(filter_frame, text="类型:").pack(side=LEFT, padx=2)
        ttk.Combobox(filter_frame, textvariable=self.manage_filter_type_var, values=["全部", "Git", "文件夹"], state="readonly", width=8).pack(side=LEFT, padx=5)

        ttk.Label(filter_frame, text="状态:").pack(side=LEFT, padx=2)
        ttk.Combobox(filter_frame, textvariable=self.manage_filter_status_var, values=["全部", "有更新", "已是最新", "未知", "检查中..."], state="readonly", width=10).pack(side=LEFT, padx=5)
        
        ttk.Separator(filter_frame, orient=VERTICAL).pack(side=LEFT, padx=10, fill=Y)
        
        ttk.Button(filter_frame, text="全选", command=self.select_all_manage, bootstyle="secondary-outline").pack(side=LEFT, padx=5)
        ttk.Button(filter_frame, text="全不选", command=self.deselect_all_manage, bootstyle="secondary-outline").pack(side=LEFT, padx=5)

        # Toolbar
        toolbar = ttk.Frame(self.tab_manage)
        toolbar.pack(fill=X, pady=5)
        
        ttk.Button(toolbar, text="刷新列表", command=self.refresh_current_nodes, bootstyle="info-outline").pack(side=LEFT, padx=5)
        ttk.Button(toolbar, text="检查更新", command=self.start_check_updates_thread, bootstyle="primary").pack(side=LEFT, padx=5)
        ttk.Button(toolbar, text="更新选中", command=self.start_update_selected_thread, bootstyle="success").pack(side=LEFT, padx=5)
        ttk.Button(toolbar, text="安装依赖", command=self.start_install_reqs_thread, bootstyle="warning").pack(side=LEFT, padx=5)
        ttk.Button(toolbar, text="修复选中", command=self.start_repair_selected_thread, bootstyle="danger-outline").pack(side=LEFT, padx=5)
        ttk.Button(toolbar, text="删除选中", command=self.start_delete_selected_thread, bootstyle="danger").pack(side=LEFT, padx=5)
        
        # Add Node
        ttk.Separator(toolbar, orient=VERTICAL).pack(side=LEFT, padx=10, fill=Y)
        self.new_node_url = tk.StringVar()
        ttk.Entry(toolbar, textvariable=self.new_node_url, width=40).pack(side=LEFT, padx=5)
        ttk.Button(toolbar, text="Git 安装节点", command=self.start_git_install_thread, bootstyle="dark").pack(side=LEFT, padx=5)

        # Treeview Frame
        tree_frame = ttk.Frame(self.tab_manage)
        tree_frame.pack(fill=BOTH, expand=True)

        columns = ("select", "name", "type", "remote", "status", "msg")
        self.manage_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="extended")
        
        self.manage_tree.heading("select", text="选择", command=lambda: self.sort_treeview(self.manage_tree, "select", False))
        self.manage_tree.heading("name", text="节点名称", command=lambda: self.sort_treeview(self.manage_tree, "name", False))
        self.manage_tree.heading("type", text="类型", command=lambda: self.sort_treeview(self.manage_tree, "type", False))
        self.manage_tree.heading("remote", text="Git 地址", command=lambda: self.sort_treeview(self.manage_tree, "remote", False))
        self.manage_tree.heading("status", text="更新状态", command=lambda: self.sort_treeview(self.manage_tree, "status", False))
        self.manage_tree.heading("msg", text="信息", command=lambda: self.sort_treeview(self.manage_tree, "msg", False))
        
        self.manage_tree.column("select", width=60, anchor=CENTER, stretch=False)
        self.manage_tree.column("name", width=200, minwidth=100)
        self.manage_tree.column("type", width=80, minwidth=60, stretch=False)
        self.manage_tree.column("remote", width=300, minwidth=150)
        self.manage_tree.column("status", width=100, minwidth=80, stretch=False)
        self.manage_tree.column("msg", width=200, minwidth=100)
        
        # Scrollbars
        v_scrollbar = ttk.Scrollbar(tree_frame, orient=VERTICAL, command=self.manage_tree.yview)
        h_scrollbar = ttk.Scrollbar(tree_frame, orient=HORIZONTAL, command=self.manage_tree.xview)
        
        self.manage_tree.configure(yscroll=v_scrollbar.set, xscroll=h_scrollbar.set)
        
        # Grid layout for tree and scrollbars
        self.manage_tree.grid(row=0, column=0, sticky='nsew')
        v_scrollbar.grid(row=0, column=1, sticky='ns')
        h_scrollbar.grid(row=1, column=0, sticky='ew')
        
        # Configure grid weights
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        # Style configuration for striped rows
        self.manage_tree.tag_configure('odd', background='#3a3a3a')
        self.manage_tree.tag_configure('even', background='#2b2b2b')
        self.manage_tree.tag_configure('checked', background='#5bc0de', foreground='#000000')
        
        self.manage_tree.bind('<Button-1>', self.on_manage_click)
        self.manage_tree.bind('<Button-3>', self.show_context_menu)
        self.manage_tree.bind('<Double-1>', self.on_node_double_click)

    def setup_migrate_tab(self):
        # Source Config
        src_frame = ttk.Frame(self.tab_migrate)
        src_frame.pack(fill=X, pady=5)
        
        ttk.Label(src_frame, text="旧版节点路径:").pack(side=LEFT, padx=5)
        ttk.Entry(src_frame, textvariable=self.old_nodes_path_var).pack(side=LEFT, fill=X, expand=True, padx=5)
        ttk.Button(src_frame, text="浏览", command=self.browse_old_nodes, bootstyle="outline").pack(side=LEFT, padx=5)
        ttk.Button(src_frame, text="扫描旧节点", command=self.scan_old_nodes, bootstyle="primary").pack(side=LEFT, padx=5)
        
        # Options & Filter
        filter_frame = ttk.Frame(self.tab_migrate)
        filter_frame.pack(fill=X, pady=5)
        
        self.hide_existing_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(filter_frame, text="隐藏已存在节点", variable=self.hide_existing_var, command=self.filter_migrate_list).pack(side=LEFT, padx=5)
        
        ttk.Separator(filter_frame, orient=VERTICAL).pack(side=LEFT, padx=10, fill=Y)
        
        ttk.Label(filter_frame, text="名称:").pack(side=LEFT, padx=2)
        ttk.Entry(filter_frame, textvariable=self.migrate_filter_var, width=15).pack(side=LEFT, padx=5)

        ttk.Label(filter_frame, text="状态:").pack(side=LEFT, padx=2)
        ttk.Combobox(filter_frame, textvariable=self.migrate_filter_status_var, values=["全部", "可迁移", "已存在", "已迁移"], state="readonly", width=10).pack(side=LEFT, padx=5)
        
        ttk.Separator(filter_frame, orient=VERTICAL).pack(side=LEFT, padx=10, fill=Y)
        
        ttk.Button(filter_frame, text="全选", command=self.select_all_migrate, bootstyle="secondary-outline").pack(side=LEFT, padx=5)
        ttk.Button(filter_frame, text="全不选", command=self.deselect_all_migrate, bootstyle="secondary-outline").pack(side=LEFT, padx=5)

        # Actions
        action_frame = ttk.Frame(self.tab_migrate)
        action_frame.pack(fill=X, pady=5)
        ttk.Button(action_frame, text="迁移选中节点", command=self.start_migration_thread, bootstyle="success").pack(side=LEFT, padx=5)
        ttk.Button(action_frame, text="直接复制选中", command=self.start_copy_thread, bootstyle="info").pack(side=LEFT, padx=5)
        ttk.Button(action_frame, text="删除选中节点", command=self.start_delete_migrate_thread, bootstyle="danger").pack(side=LEFT, padx=5)
        
        # Treeview
        columns = ("select", "name", "remote", "target_status")
        self.migrate_tree = ttk.Treeview(self.tab_migrate, columns=columns, show="headings", selectmode="extended")
        
        self.migrate_tree.heading("select", text="选择")
        self.migrate_tree.heading("name", text="节点名称")
        self.migrate_tree.heading("remote", text="Git 地址")
        self.migrate_tree.heading("target_status", text="目标状态")
        
        self.migrate_tree.column("select", width=80, anchor=CENTER)
        self.migrate_tree.column("name", width=200)
        self.migrate_tree.column("remote", width=400)
        self.migrate_tree.column("target_status", width=150)
        
        scrollbar = ttk.Scrollbar(self.tab_migrate, orient=VERTICAL, command=self.migrate_tree.yview)
        self.migrate_tree.configure(yscroll=scrollbar.set)
        
        self.migrate_tree.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)
        self.migrate_tree.bind('<Button-1>', self.on_migrate_click)

    # --- Helpers ---
    def log(self, msg):
        print(msg)

    def on_manage_click(self, event):
        col = self.manage_tree.identify_column(event.x)
        if col != '#1':
            return
        iid = self.manage_tree.identify_row(event.y)
        if not iid:
            return
        val = self.manage_tree.set(iid, 'select')
        new_val = '☑' if val != '☑' else '☐'
        self.manage_tree.set(iid, 'select', new_val)
        
        # Update Tags (Exclusive logic: Checked OR Odd/Even)
        if new_val == '☑':
            self.manage_checked.add(iid)
            self.manage_tree.item(iid, tags=['checked'])
        else:
            self.manage_checked.discard(iid)
            # Restore odd/even based on index
            idx = self.manage_tree.index(iid)
            tag = 'even' if idx % 2 == 0 else 'odd'
            self.manage_tree.item(iid, tags=[tag])

    def show_context_menu(self, event):
        iid = self.manage_tree.identify_row(event.y)
        if iid:
            # Select the row if not already selected
            if iid not in self.manage_tree.selection():
                self.manage_tree.selection_set(iid)
                
            menu = tk.Menu(self, tearoff=0)
            values = self.manage_tree.item(iid)['values']
            node_name = values[1]
            remote_url = values[3]
            
            menu.add_command(label="复制名称", command=lambda: self.copy_to_clipboard(node_name))
            
            if remote_url and remote_url != "-":
                menu.add_command(label="复制地址", command=lambda: self.copy_to_clipboard(remote_url))
                menu.add_command(label="打开 GitHub", command=lambda: webbrowser.open(remote_url))
            else:
                menu.add_command(label="在 GitHub 搜索", command=lambda: webbrowser.open(f"https://github.com/search?q={node_name}"))
                menu.add_command(label="设置 Git 地址", command=lambda: self.set_git_url(node_name))
                
            menu.post(event.x_root, event.y_root)

    def set_git_url(self, node_name):
        url = simpledialog.askstring("设置 Git 地址", f"请输入 {node_name} 的 Git 仓库地址:", parent=self)
        if not url:
            return
            
        url = url.strip()
        if not url:
            return

        # Validation Logic
        # We need to check if the content of the repo at 'url' matches the local folder content.
        # This is tricky without cloning.
        # A simple approach: 
        # 1. Warn user that this action will just associate the URL for future use (like migration), 
        #    but won't convert the current folder to a git repo immediately unless we implement that.
        # 
        # Requirement: "提交地址后，需要对地址进行验证，如果是这个地址，那么才更新信息，如果有差异，请告知用户，用户可以强制提交或者取消"
        # 
        # To validate:
        # We can try to list files from the remote repo (e.g. using git ls-remote or fetching a file list via API if it's GitHub)
        # But git ls-remote only gives refs.
        # 
        # Better approach for verification:
        # 1. Clone the repo to a temp dir.
        # 2. Compare file structure/names with local dir.
        # 3. If similar, assume correct.
        
        threading.Thread(target=self.verify_and_set_git_url, args=(node_name, url), daemon=True).start()

    def verify_and_set_git_url(self, node_name, url):
        self.log(f"正在验证 Git 地址: {url} ...")
        
        import tempfile
        temp_dir = os.path.join(tempfile.gettempdir(), "comfynode_sync_validate", node_name)
        
        if os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except:
                pass
                
        try:
            # Clone to temp
            self.manager.clone_node(url, temp_dir, proxy=self.get_proxy_url())
            
            # Compare
            local_path = os.path.join(self.custom_nodes_path_var.get(), node_name)
            
            # Get file lists
            local_files = set()
            for root, dirs, files in os.walk(local_path):
                rel_root = os.path.relpath(root, local_path)
                if rel_root == ".": rel_root = ""
                for f in files:
                    if not f.endswith(".pyc") and ".git" not in root:
                        local_files.add(os.path.join(rel_root, f))

            remote_files = set()
            for root, dirs, files in os.walk(temp_dir):
                rel_root = os.path.relpath(root, temp_dir)
                if rel_root == ".": rel_root = ""
                if ".git" in root: continue
                for f in files:
                    remote_files.add(os.path.join(rel_root, f))
            
            # Calculate similarity (Jaccard index or simple intersection)
            intersection = local_files.intersection(remote_files)
            similarity = len(intersection) / len(local_files.union(remote_files)) if local_files or remote_files else 0
            
            is_match = similarity > 0.5 # Threshold
            
            msg = f"验证完成。\n相似度: {similarity:.2%}\n"
            if is_match:
                msg += "文件结构高度匹配，已自动更新地址。"
                self.manager.set_node_git_url(node_name, url)
                self.log(f"Git 地址更新成功: {node_name} -> {url}")
                messagebox.showinfo("验证成功", msg)
                self.after(100, self.refresh_current_nodes)
            else:
                msg += "文件结构差异较大，可能不是同一个节点。\n是否强制设置为此地址？"
                if messagebox.askyesno("验证差异", msg):
                    self.manager.set_node_git_url(node_name, url)
                    self.log(f"用户强制更新 Git 地址: {node_name} -> {url}")
                    self.after(100, self.refresh_current_nodes)
                else:
                    self.log("用户取消更新 Git 地址。")
            
            # Clean up
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except:
                pass
                
        except Exception as e:
            self.log(f"验证失败: {e}")
            if messagebox.askyesno("验证出错", f"验证过程中出错：{e}\n是否忽略错误强制设置？"):
                 self.manager.set_node_git_url(node_name, url)
                 self.log(f"用户强制更新 Git 地址: {node_name} -> {url}")
                 self.after(100, self.refresh_current_nodes)

    def copy_to_clipboard(self, text):
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update() # Required to keep clipboard after closing

    def on_node_double_click(self, event):
        item = self.manage_tree.selection()
        if not item: return
        # selection() returns a tuple of iids
        iid = item[0]
        values = self.manage_tree.item(iid)['values']
        node_name = values[1]
        remote_url = values[3]
        
        if remote_url and remote_url != "-":
            webbrowser.open(remote_url)
        else:
            webbrowser.open(f"https://github.com/search?q={node_name}")

    def on_migrate_click(self, event):
        col = self.migrate_tree.identify_column(event.x)
        if col != '#1':
            return
        iid = self.migrate_tree.identify_row(event.y)
        if not iid:
            return
        val = self.migrate_tree.set(iid, 'select')
        new_val = '☑' if val != '☑' else '☐'
        self.migrate_tree.set(iid, 'select', new_val)
        if new_val == '☑':
            self.migrate_checked.add(iid)
        else:
            self.migrate_checked.discard(iid)

    def load_config(self):
        # Config is also relative to script
        base_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(base_dir, CONFIG_FILE)
        
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    config = json.load(f)
                    self.comfy_root_var.set(config.get("comfy_root", ""))
                    self.python_path_var.set(config.get("python_path", ""))
                    self.proxy_var.set(config.get("proxy", ""))
                    self.old_nodes_path_var.set(config.get("old_nodes_path", ""))
                    self.symlink_source_var.set(config.get("symlink_source", ""))
                    self.workflow_source_var.set(config.get("workflow_source", ""))
                    self.symlink_target_var.set(config.get("symlink_target", ""))
                    self.model_target_var.set(config.get("model_target", ""))
                    self.workflow_target_var.set(config.get("workflow_target", ""))
                    self.update_paths_from_root()
            except Exception as e:
                self.log(f"Config load error: {e}")

    def save_config(self):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(base_dir, CONFIG_FILE)
        
        config = {
            "comfy_root": self.comfy_root_var.get(),
            "python_path": self.python_path_var.get(),
            "proxy": self.proxy_var.get(),
            "old_nodes_path": self.old_nodes_path_var.get(),
            "symlink_source": self.symlink_source_var.get(),
            "workflow_source": self.workflow_source_var.get(),
            "symlink_target": self.symlink_target_var.get(),
            "model_target": self.model_target_var.get(),
            "workflow_target": self.workflow_target_var.get()
        }
        try:
            with open(config_path, 'w') as f:
                json.dump(config, f)
            self.log("Configuration saved.")
        except Exception as e:
            self.log(f"Config save error: {e}")

    def update_paths_from_root(self):
        root = self.comfy_root_var.get()
        if root and os.path.isdir(root):
            # Infer custom_nodes
            cn_path = os.path.join(root, "ComfyUI", "custom_nodes") # Standard install
            if not os.path.exists(cn_path):
                cn_path = os.path.join(root, "custom_nodes") # Portable root might be the ComfyUI folder itself
            
            self.custom_nodes_path_var.set(cn_path)
            
            # Infer python if not set
            if not self.python_path_var.get():
                py_path = os.path.join(root, "python_embeded", "python.exe")
                if os.path.exists(py_path):
                    self.python_path_var.set(py_path)
                    self.log(f"Auto-detected Python: {py_path}")

    def browse_comfy_root(self):
        path = filedialog.askdirectory()
        if path:
            self.comfy_root_var.set(path)
            self.update_paths_from_root()
            self.refresh_current_nodes()

    def browse_python(self):
        path = filedialog.askopenfilename(filetypes=[("Executables", "*.exe"), ("All Files", "*.*")])
        if path:
            self.python_path_var.set(path)

    def browse_old_nodes(self):
        path = filedialog.askdirectory()
        if path:
            self.old_nodes_path_var.set(path)

    # --- Manage Tab Logic ---
    def refresh_current_nodes(self):
        path = self.custom_nodes_path_var.get()
        if not path or not os.path.exists(path):
            self.log("Custom nodes path not found. Please set ComfyUI Root correctly.")
            return

        self.current_nodes = []
        
        try:
            self.log(f"Scanning {path}...")
            nodes = self.manager.scan_directory(path)
            self.current_nodes = nodes
            self.update_manage_list()
            self.log(f"Loaded {len(nodes)} nodes.")
        except Exception as e:
            self.log(f"Scan failed: {e}")

    def update_manage_list(self):
        self.manage_tree.delete(*self.manage_tree.get_children())
        self.manage_checked.clear()
        
        filter_name = self.manage_filter_name_var.get().lower()
        filter_type = self.manage_filter_type_var.get()
        filter_status = self.manage_filter_status_var.get()
        
        for node in self.current_nodes:
            # 1. Name Filter
            if filter_name and filter_name not in node.name.lower():
                continue
            
            # 2. Type Filter
            is_git = node.is_git_repo
            # Check if it has a manual URL - although now node.is_git_repo might be True for manual ones too
            # We can rely on is_git_repo being True now
            
            node_type_str = "Git" if is_git else "文件夹"
            if filter_type != "全部" and filter_type != node_type_str:
                continue
                
            # 3. Status Filter
            status = self.node_status_map.get(node.name, "未知")
            # If checking in progress, we might have stored it or not. 
            # If status not in map, it defaults to "未知".
            if filter_status != "全部" and filter_status != status:
                 continue
                
            msg_val = ""
            if node.last_update_time:
                msg_val = f"最后更新: {node.last_update_time}"
            
            # Use cached status
            tag = 'even' if self.manage_tree.get_children() and len(self.manage_tree.get_children()) % 2 == 0 else 'odd'
            self.manage_tree.insert("", END, values=(
                "☐",
                node.name,
                node_type_str,
                node.remote_url if node.remote_url else "-",
                status,
                msg_val
            ), tags=(tag,))

    def sort_treeview(self, tree, col, reverse):
        l = [(tree.set(k, col), k) for k in tree.get_children('')]
        l.sort(reverse=reverse)

        # rearrange items in sorted positions
        for index, (val, k) in enumerate(l):
            tree.move(k, '', index)
            
            # Apply tags based on state
            if tree.set(k, 'select') == '☑':
                tree.item(k, tags=['checked'])
            else:
                tag = 'even' if index % 2 == 0 else 'odd'
                tree.item(k, tags=[tag])

        # reverse sort next time
        tree.heading(col, command=lambda: self.sort_treeview(tree, col, not reverse))

    def select_all_manage(self):
        for item_id in self.manage_tree.get_children():
            self.manage_tree.set(item_id, "select", "☑")
            self.manage_checked.add(item_id)
            self.manage_tree.item(item_id, tags=['checked'])

    def deselect_all_manage(self):
        for index, item_id in enumerate(self.manage_tree.get_children()):
            self.manage_tree.set(item_id, "select", "☐")
            self.manage_checked.discard(item_id)
            tag = 'even' if index % 2 == 0 else 'odd'
            self.manage_tree.item(item_id, tags=[tag])

    def start_check_updates_thread(self):
        threading.Thread(target=self.check_updates_logic, daemon=True).start()

    def check_updates_logic(self):
        proxy = self.get_proxy_url()
        self.log("Checking for updates...")
        
        # We need to iterate over all nodes, not just visible ones, 
        # or at least update the status map so filtering works later.
        # But for performance and feedback, let's iterate visible items first or all nodes?
        # Better to iterate current_nodes (all data) and update map, then refresh UI.
        
        # However, checking update is slow. We should update UI incrementally.
        # Let's iterate over visible items in treeview first to give feedback?
        # Or better: Iterate all Git nodes in background, update map, and if item is visible, update treeview.
        
        # Let's simple implementation: Iterate all current_nodes.
        total = len(self.current_nodes)
        count = 0
        
        for node in self.current_nodes:
            if not node.is_git_repo:
                self.node_status_map[node.name] = "不适用"
                continue
                
            count += 1
            # Update status to checking...
            self.node_status_map[node.name] = "检查中..."
            # Try to update UI row if exists
            self.update_single_node_ui(node.name)
            
            node_path = os.path.join(self.custom_nodes_path_var.get(), node.name)
            try:
                has_update = self.manager.check_update(node_path, proxy=proxy if proxy else None)
                status = "有更新" if has_update else "已是最新"
                self.node_status_map[node.name] = status
            except Exception as e:
                self.node_status_map[node.name] = "检查失败"
            
            self.update_single_node_ui(node.name)
            
        self.log("Update check finished.")

    def update_single_node_ui(self, node_name):
        # Find item in treeview
        for item_id in self.manage_tree.get_children():
            if self.manage_tree.item(item_id, "values")[1] == node_name:
                status = self.node_status_map.get(node_name, "未知")
                self.manage_tree.set(item_id, column="status", value=status)
                break

    def start_update_selected_thread(self):
        threading.Thread(target=self.update_selected_logic, daemon=True).start()

    def start_delete_selected_thread(self):
        threading.Thread(target=self.delete_selected_logic, daemon=True).start()

    def delete_selected_logic(self):
        checked = list(self.manage_checked)
        selected = self.manage_tree.selection()
        items = checked if checked else selected
        if not items:
            self.log("No nodes selected.")
            return
        count = len(items)
        if not messagebox.askyesno("确认删除", f"确认删除选中的 {count} 个节点？此操作不可恢复！"):
            self.log("Delete cancelled.")
            return
        root = self.custom_nodes_path_var.get()
        if not root:
            self.log("Custom nodes path not set.")
            return
        for item_id in items:
            values = self.manage_tree.item(item_id)['values']
            name = values[1]
            node_path = os.path.join(root, name)
            try:
                self.log(f"Deleting {name}...")
                self.manager.delete_node(node_path)
                self.manager.remove_node_metadata(name)
                self.manage_tree.delete(item_id)
                self.log(f"Deleted {name}.")
            except Exception as e:
                self.log(f"Failed to delete {name}: {e}")

    def update_selected_logic(self):
        checked = list(self.manage_checked)
        selected = self.manage_tree.selection()
        items = checked if checked else selected
        if not items:
            self.log("No nodes selected.")
            return
            
        proxy = self.get_proxy_url()
        self.log(f"Starting update for {len(selected)} node(s)...")
        
        for item_id in items:
            values = self.manage_tree.item(item_id)['values']
            name = values[1]
            node_path = os.path.join(self.custom_nodes_path_var.get(), name)
            
            if values[2] == "Git":
                self.log(f"Updating {name}...")
                try:
                    summary = self.manager.pull_node(node_path, proxy=proxy if proxy else None)
                    
                    # Get additional info
                    commit_info = self.manager.get_last_commit_info(node_path)
                    
                    # Update timestamp
                    timestamp = self.manager.update_node_timestamp(node_path)
                    
                    new_status = "已更新"
                    self.node_status_map[name] = new_status
                    self.manage_tree.set(item_id, column="status", value=new_status)
                    self.manage_tree.set(item_id, column="msg", value=f"最后更新: {timestamp}")
                    self.log(f"Updated {name}:\n{summary}\n\n[Current Version Info]\n{commit_info}\n" + "-"*40)
                except Exception as e:
                    self.log(f"Failed to update {name}: {e}")
                    self.manage_tree.set(item_id, column="msg", value="更新失败")
            else:
                self.log(f"Skipping {name}: Not a git repository.")

    def start_install_reqs_thread(self):
        threading.Thread(target=self.install_reqs_logic, daemon=True).start()

    def start_repair_selected_thread(self):
        threading.Thread(target=self.repair_selected_logic, daemon=True).start()

    def repair_selected_logic(self):
        checked = list(self.manage_checked)
        selected = self.manage_tree.selection()
        items = checked if checked else selected
        if not items:
            self.log("没有选择节点。")
            return

        if not messagebox.askyesno("确认修复", f"将尝试重新安装选中的 {len(items)} 个节点。\n这将删除现有文件夹并重新克隆。\n是否继续？"):
            return

        target_root = self.custom_nodes_path_var.get()
        proxy = self.get_proxy_url()

        self.log(f"开始修复 {len(items)} 个节点...")

        for item_id in items:
            values = self.manage_tree.item(item_id)['values']
            name = values[1]
            node_type = values[2]
            remote_url = values[3]
            
            node_path = os.path.join(target_root, name)

            if node_type != "Git" or not remote_url or remote_url == "-":
                self.log(f"跳过 {name}: 不是 Git 仓库或无远程地址，无法自动修复。")
                continue

            self.log(f"正在修复 {name} (重新安装)...")
            try:
                # 1. Delete
                self.log(f"  正在删除 {name}...")
                self.manager.delete_node(node_path)
                
                # 2. Clone
                self.log(f"  正在重新克隆 {name}...")
                summary = self.manager.clone_node(remote_url, node_path, proxy=proxy if proxy else None)
                
                # 3. Update UI
                self.manage_tree.set(item_id, column="status", value="已修复")
                self.manage_tree.set(item_id, column="msg", value="重新安装成功")
                self.log(f"修复成功 {name}:\n{summary}\n" + "-"*40)
            except Exception as e:
                self.log(f"修复失败 {name}: {e}")
                self.manage_tree.set(item_id, column="msg", value="修复失败")
    
    def install_reqs_logic(self):
        selected = self.manage_tree.selection()
        if not selected:
             selected = self.manage_tree.get_children() # If none selected, do all? No, maybe risky. Let's do selected only or warn.
             self.log("No nodes selected. Please select nodes to install requirements.")
             return

        python_path = self.python_path_var.get()
        if not python_path or not os.path.exists(python_path):
            self.log("Invalid Python path.")
            return

        proxy = self.get_proxy_url()

        for item_id in selected:
            values = self.manage_tree.item(item_id)['values']
            name = values[0]
            node_path = os.path.join(self.custom_nodes_path_var.get(), name)
            
            try:
                self.manager.install_requirements(node_path, python_path, proxy=proxy if proxy else None)
                self.manage_tree.set(item_id, column="msg", value="Deps Installed")
            except Exception as e:
                self.manage_tree.set(item_id, column="msg", value="Deps Failed")

    def start_git_install_thread(self):
        url = self.new_node_url.get().strip()
        if not url: return
        threading.Thread(target=self.git_install_logic, args=(url,), daemon=True).start()

    def git_install_logic(self, url):
        target_root = self.custom_nodes_path_var.get()
        if not target_root:
            self.log("Custom nodes path not set.")
            return
            
        # Infer name from URL
        name = url.split("/")[-1]
        if name.endswith(".git"): name = name[:-4]
        
        target_path = os.path.join(target_root, name)
        proxy = self.get_proxy_url()
        
        self.log(f"Cloning {name} from {url}...")
        try:
            summary = self.manager.clone_node(url, target_path, proxy=proxy if proxy else None)
            self.log(f"Installed {name}:\n{summary}\n" + "-"*40)
            self.new_node_url.set("") # Clear input
            self.refresh_current_nodes() # Refresh list
        except Exception as e:
            self.log(f"Installation failed: {e}")

    # --- Migrate Tab Logic ---
    def scan_old_nodes(self):
        path = self.old_nodes_path_var.get()
        if not path or not os.path.exists(path):
            self.log("Invalid old nodes path.")
            return
            
        self.migration_nodes = []
        
        try:
            nodes = self.manager.scan_directory(path)
            self.migration_nodes = nodes
            self.filter_migrate_list()
            self.log(f"Scanned {len(nodes)} old nodes.")
        except Exception as e:
            self.log(f"Scan failed: {e}")

    def filter_migrate_list(self):
        self.migrate_tree.delete(*self.migrate_tree.get_children())
        self.migrate_checked.clear()
        current_target_root = self.custom_nodes_path_var.get()
        hide_existing = self.hide_existing_var.get()
        filter_text = self.migrate_filter_var.get().lower()
        filter_status = self.migrate_filter_status_var.get()

        for node in self.migration_nodes:
            if filter_text and filter_text not in node.name.lower():
                continue

            status = "未知"
            is_existing = False
            
            if current_target_root:
                if os.path.exists(os.path.join(current_target_root, node.name)):
                    status = "已存在（跳过）"
                    is_existing = True
                else:
                    status = "可迁移"
            
            # Existing logic
            if hide_existing and is_existing:
                continue
                
            # New Status Filter
            # Status can be "已存在（跳过）", "可迁移", "已迁移（Git）", "已跳过（非Git）", "已复制"
            # Simplify mapping for user convenience? 
            # Dropdown values: ["全部", "可迁移", "已存在", "已迁移"]
            
            if filter_status != "全部":
                if filter_status == "可迁移" and status != "可迁移":
                    continue
                elif filter_status == "已存在" and "已存在" not in status:
                    continue
                elif filter_status == "已迁移" and ("已迁移" not in status and "已复制" not in status):
                    continue

            self.migrate_tree.insert("", END, values=(
                "☐",
                node.name,
                node.remote_url if node.remote_url else "Local Dir",
                status
            ))

    def select_all_migrate(self):
        for item_id in self.migrate_tree.get_children():
            self.migrate_tree.set(item_id, "select", "☑")
            self.migrate_checked.add(item_id)

    def deselect_all_migrate(self):
        for item_id in self.migrate_tree.get_children():
            self.migrate_tree.set(item_id, "select", "☐")
            self.migrate_checked.discard(item_id)

    def start_migration_thread(self):
        threading.Thread(target=self.migration_logic, daemon=True).start()

    def start_copy_thread(self):
        threading.Thread(target=self.copy_selected_logic, daemon=True).start()

    def start_delete_migrate_thread(self):
        threading.Thread(target=self.delete_migrate_logic, daemon=True).start()

    def migration_logic(self):
        checked = list(self.migrate_checked)
        selected = self.migrate_tree.selection()
        target_root = self.custom_nodes_path_var.get()
        proxy = self.get_proxy_url()
        
        if not target_root:
            self.log("Target custom_nodes path not set.")
            return

        items_to_process = checked if checked else (selected if selected else self.migrate_tree.get_children())
        
        for item_id in items_to_process:
            values = self.migrate_tree.item(item_id)['values']
            name = values[1]
            status = values[3]
            
            if "Exists" in status or "已存在" in status:
                continue
                
            # Find node object
            node = next((n for n in self.migration_nodes if n.name == name), None)
            if not node: continue
            
            target_path = os.path.join(target_root, name)
            
            if node.is_git_repo and node.remote_url:
                self.log(f"Migrating {name} (Git Clone)...")
                try:
                    summary = self.manager.clone_node(node.remote_url, target_path, proxy=proxy if proxy else None)
                    self.migrate_tree.set(item_id, column="target_status", value="已迁移（Git）")
                    self.log(f"Migrated {name}:\n{summary}\n" + "-"*40)
                except Exception as e:
                    self.log(f"Migration failed for {name}: {e}")
            else:
                self.migrate_tree.set(item_id, column="target_status", value="已跳过（非Git）")
                self.log(f"Skipping {name}: Non-Git or no remote. Migration only supports Git clone.")

    def copy_selected_logic(self):
        checked = list(self.migrate_checked)
        selected = self.migrate_tree.selection()
        items = checked if checked else selected
        
        target_root = self.custom_nodes_path_var.get()
        source_root = self.old_nodes_path_var.get()
        
        if not items:
            self.log("没有选择节点。")
            return
            
        if not target_root or not source_root:
            self.log("目标或源路径未设置。")
            return

        for item_id in items:
            values = self.migrate_tree.item(item_id)['values']
            name = values[1]
            status = values[3]
            
            if "已存在" in status or "已迁移" in status or "已复制" in status:
                self.log(f"跳过 {name}: 目标已存在。")
                continue
                
            source_path = os.path.join(source_root, name)
            target_path = os.path.join(target_root, name)
            
            if not os.path.exists(source_path):
                self.log(f"错误: 源路径不存在 {source_path}")
                continue
                
            self.log(f"正在复制 {name} ...")
            try:
                if os.path.isdir(source_path):
                    shutil.copytree(source_path, target_path)
                else:
                    shutil.copy2(source_path, target_path) # Should be dirs usually, but just in case
                    
                self.migrate_tree.set(item_id, column="target_status", value="已复制")
                self.log(f"已复制 {name}")
            except Exception as e:
                self.log(f"复制失败 {name}: {e}")

    def delete_migrate_logic(self):
        checked = list(self.migrate_checked)
        selected = self.migrate_tree.selection()
        items = checked if checked else selected
        if not items:
            self.log("No nodes selected.")
            return
        if not messagebox.askyesno("确认删除", f"确认删除目标环境中的 {len(items)} 个节点？此操作不可恢复！"):
            self.log("Delete cancelled.")
            return
        target_root = self.custom_nodes_path_var.get()
        if not target_root:
            self.log("Target custom_nodes path not set.")
            return
        for item_id in items:
            values = self.migrate_tree.item(item_id)['values']
            name = values[1]
            target_path = os.path.join(target_root, name)
            try:
                if os.path.exists(target_path):
                    self.log(f"Deleting {name} from target...")
                    self.manager.delete_node(target_path)
                    self.manager.remove_node_metadata(name)
                    self.migrate_tree.set(item_id, column="target_status", value="可迁移")
                    self.log(f"Deleted {name}.")
                else:
                    self.migrate_tree.set(item_id, column="target_status", value="可迁移")
                    self.log(f"Target node {name} not found. Marked as 可迁移.")
            except Exception as e:
                self.log(f"Failed to delete {name}: {e}")

    # --- Symlink Tab Logic ---
    def setup_symlink_tab(self):
        # Target (New ComfyUI Instance) - Shared for both
        target_frame = ttk.Labelframe(self.tab_symlink, text="基础设置 (可选)", padding=10)
        target_frame.pack(fill=X, padx=5, pady=5)
        
        ttk.Label(target_frame, text="ComfyUI 实例路径 (自动填充目标):").grid(row=0, column=0, sticky=W, padx=5)
        ttk.Entry(target_frame, textvariable=self.symlink_target_var).grid(row=0, column=1, sticky=EW, padx=5)
        ttk.Button(target_frame, text="浏览", command=self.browse_symlink_target, bootstyle="outline").grid(row=0, column=2, padx=5)
        target_frame.columnconfigure(1, weight=1)
        
        self.symlink_target_var.trace("w", self.on_target_root_change)

        # Source (Shared Models)
        src_frame = ttk.Labelframe(self.tab_symlink, text="大模型共享 (Shared Models)", padding=10)
        src_frame.pack(fill=X, padx=5, pady=5)
        
        ttk.Label(src_frame, text="源模型路径:").grid(row=0, column=0, sticky=W, padx=5)
        ttk.Entry(src_frame, textvariable=self.symlink_source_var).grid(row=0, column=1, sticky=EW, padx=5)
        ttk.Button(src_frame, text="浏览", command=self.browse_symlink_source, bootstyle="outline").grid(row=0, column=2, padx=5)
        
        ttk.Label(src_frame, text="目标模型路径:").grid(row=1, column=0, sticky=W, padx=5)
        ttk.Entry(src_frame, textvariable=self.model_target_var).grid(row=1, column=1, sticky=EW, padx=5)
        ttk.Button(src_frame, text="浏览", command=self.browse_model_target, bootstyle="outline").grid(row=1, column=2, padx=5)
        
        ttk.Button(src_frame, text="创建模型软链", command=self.start_symlink_thread, bootstyle="success").grid(row=0, column=3, rowspan=2, padx=5, sticky=NS)
        
        src_frame.columnconfigure(1, weight=1)
        
        # Source (Shared Workflows)
        wf_frame = ttk.Labelframe(self.tab_symlink, text="工作流共享 (Shared Workflows)", padding=10)
        wf_frame.pack(fill=X, padx=5, pady=5)
        
        ttk.Label(wf_frame, text="源工作流路径:").grid(row=0, column=0, sticky=W, padx=5)
        ttk.Entry(wf_frame, textvariable=self.workflow_source_var).grid(row=0, column=1, sticky=EW, padx=5)
        ttk.Button(wf_frame, text="浏览", command=self.browse_workflow_source, bootstyle="outline").grid(row=0, column=2, padx=5)
        
        ttk.Label(wf_frame, text="目标工作流路径:").grid(row=1, column=0, sticky=W, padx=5)
        ttk.Entry(wf_frame, textvariable=self.workflow_target_var).grid(row=1, column=1, sticky=EW, padx=5)
        ttk.Button(wf_frame, text="浏览", command=self.browse_workflow_target, bootstyle="outline").grid(row=1, column=2, padx=5)
        
        ttk.Button(wf_frame, text="创建工作流软链", command=self.start_workflow_symlink_thread, bootstyle="info").grid(row=0, column=3, rowspan=2, padx=5, sticky=NS)
        
        wf_frame.columnconfigure(1, weight=1)

        # Tutorial / Info
        info_frame = ttk.Labelframe(self.tab_symlink, text="说明与教程", padding=10)
        info_frame.pack(fill=BOTH, expand=True, padx=5, pady=5)
        
        info_text = """功能说明：
1. 模型共享：将大模型文件夹链接到指定目标位置，节省硬盘空间。
   - 默认目标：[ComfyUI 实例路径]\\models

2. 工作流共享：将工作流文件夹链接到指定目标位置，方便统一管理。
   - 默认目标：[ComfyUI 实例路径]\\user\\default\\workflows
   
注意：创建软链会移除目标位置原有的同名文件夹，请提前备份重要数据！
"""
        lbl = tk.Label(info_frame, text=info_text, justify=LEFT, anchor="nw", bg="#2b2b2b", fg="#cccccc", font=("Microsoft YaHei", 10))
        lbl.pack(fill=BOTH, expand=True)

    def on_target_root_change(self, *args):
        root = self.symlink_target_var.get()
        if root and os.path.isdir(root):
            # Only auto-fill if empty? Or always?
            # Let's auto-fill if empty to avoid overwriting user changes if they just tweak the root.
            # Actually, if root changes, it's likely a new target. But user might have custom setup.
            # Let's check if current values start with old root? No, too complex.
            # Just fill if empty.
            if not self.model_target_var.get():
                self.model_target_var.set(os.path.join(root, "models"))
            if not self.workflow_target_var.get():
                self.workflow_target_var.set(os.path.join(root, "user", "default", "workflows"))

    def browse_model_target(self):
        path = filedialog.askdirectory()
        if path:
            self.model_target_var.set(path)

    def browse_workflow_target(self):
        path = filedialog.askdirectory()
        if path:
            self.workflow_target_var.set(path)

    def browse_symlink_source(self):
        path = filedialog.askdirectory()
        if path:
            self.symlink_source_var.set(path)

    def browse_workflow_source(self):
        path = filedialog.askdirectory()
        if path:
            self.workflow_source_var.set(path)

    def browse_symlink_target(self):
        path = filedialog.askdirectory()
        if path:
            self.symlink_target_var.set(path)

    def start_symlink_thread(self):
        threading.Thread(target=self.symlink_logic, daemon=True).start()
        
    def start_workflow_symlink_thread(self):
        threading.Thread(target=self.workflow_symlink_logic, daemon=True).start()

    def workflow_symlink_logic(self):
        source = self.workflow_source_var.get()
        target_workflows = self.workflow_target_var.get()
        
        if not source or not os.path.exists(source):
            self.log("错误: 源工作流路径无效")
            return
        
        if not target_workflows:
            self.log("错误: 目标工作流路径无效")
            return
        
        # Safety Check
        comfy_root = self.symlink_target_var.get()
        if comfy_root and os.path.normpath(target_workflows) == os.path.normpath(comfy_root):
            self.log("错误: 目标路径不能是 ComfyUI 根目录！请指定到 workflows 子目录。")
            messagebox.showerror("错误", "目标路径不能是 ComfyUI 根目录！\n请修改为例如: ...\\user\\default\\workflows")
            return
            
        # Target path: e.g. .../user/default/workflows
        target_parent = os.path.dirname(target_workflows)
        
        # Ensure parent dirs exist
        if not os.path.exists(target_parent):
            try:
                os.makedirs(target_parent)
            except Exception as e:
                self.log(f"无法创建目录 {target_parent}: {e}")
                return

        # Check if target exists
        if os.path.exists(target_workflows):
            if os.path.islink(target_workflows):
                 self.log(f"提示: 目标 {target_workflows} 已经是一个软链接。")
            else:
                if os.path.isdir(target_workflows):
                    confirm = messagebox.askyesno("确认操作", f"目标位置存在 workflows 文件夹：\n{target_workflows}\n\n创建软链需要删除此文件夹。\n确认删除吗？")
                    if not confirm:
                        self.log("操作取消")
                        return
                    try:
                        shutil.rmtree(target_workflows)
                    except Exception as e:
                        self.log(f"删除失败: {e}")
                        return
                else:
                    self.log(f"错误: 目标位置存在同名文件: {target_workflows}")
                    return

        # Create Symlink
        cmd = f'mklink /D "{target_workflows}" "{source}"'
        self.log(f"执行命令: {cmd}")
        
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if result.returncode == 0:
                self.log("工作流软链创建成功！")
                messagebox.showinfo("成功", "工作流软链创建成功！")
            else:
                self.log(f"创建失败 (Exit Code {result.returncode}):\n{result.stderr}\n{result.stdout}")
                if "privilege" in result.stderr.lower() or "权限" in result.stderr:
                    if messagebox.askyesno("权限不足", "需要管理员权限。是否尝试以管理员身份执行？"):
                         self.run_as_admin(cmd)
        except Exception as e:
            self.log(f"执行出错: {e}")

    def symlink_logic(self):
        source = self.symlink_source_var.get()
        target_models = self.model_target_var.get()
        
        if not source or not os.path.exists(source):
            self.log("错误: 源模型路径无效")
            return
        
        if not target_models:
            self.log("错误: 目标模型路径无效")
            return
        
        # Safety Check 1: Do not delete root
        comfy_root = self.symlink_target_var.get()
        if comfy_root and os.path.normpath(target_models) == os.path.normpath(comfy_root):
            self.log("错误: 目标路径不能是 ComfyUI 根目录！请指定到 models 子目录。")
            messagebox.showerror("错误", "目标路径不能是 ComfyUI 根目录！\n请修改为例如: ...\\ComfyUI\\models")
            return

        # Safety Check 2: Do not delete if .git exists in root (double check)
        if os.path.exists(os.path.join(target_models, ".git")):
             self.log("错误: 目标目录包含 .git 文件夹，可能是代码仓库根目录，禁止删除！")
             messagebox.showerror("错误", "目标目录看起来像是一个 Git 仓库根目录 (包含 .git)，禁止删除！\n请检查路径是否正确。")
             return

        # Check if target models exists
        if os.path.exists(target_models):
            # Check if it is already a symlink
            if os.path.islink(target_models):
                 self.log(f"提示: 目标 {target_models} 已经是一个软链接。")
            else:
                if os.path.isdir(target_models):
                    confirm = messagebox.askyesno("确认操作", f"目标位置存在 models 文件夹：\n{target_models}\n\n创建软链需要删除此文件夹。\n确认删除吗？(建议先备份重要文件)")
                    if not confirm:
                        self.log("操作取消")
                        return
                    
                    try:
                        self.log(f"正在删除原有 models 文件夹: {target_models}")
                        
                        # Handle read-only files (like git objects)
                        def onerror(func, path, exc_info):
                            import stat
                            if not os.access(path, os.W_OK):
                                os.chmod(path, stat.S_IWUSR)
                                func(path)
                            else:
                                raise

                        shutil.rmtree(target_models, onerror=onerror)
                    except Exception as e:
                        self.log(f"删除失败: {e}")
                        return
                else:
                    self.log(f"错误: 目标位置存在同名文件: {target_models}")
                    return

        # Create Symlink
        cmd = f'mklink /D "{target_models}" "{source}"'
        self.log(f"执行命令: {cmd}")
        
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if result.returncode == 0:
                self.log("软链创建成功！")
                messagebox.showinfo("成功", "软链创建成功！")
            else:
                self.log(f"创建失败 (Exit Code {result.returncode}):\n{result.stderr}\n{result.stdout}")
                if "privilege" in result.stderr.lower() or "权限" in result.stderr:
                    self.log("提示: 请尝试以管理员身份运行此程序")
                    if messagebox.askyesno("权限不足", "创建软链需要管理员权限。是否尝试以管理员身份执行命令？"):
                         self.run_as_admin(cmd)
        except Exception as e:
            self.log(f"执行出错: {e}")

    def run_as_admin(self, cmd):
        try:
             ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", "cmd.exe", f"/c {cmd} & pause", None, 1)
             if ret > 32:
                 self.log("已请求管理员权限执行命令，请查看弹出的 CMD 窗口。")
             else:
                 self.log(f"请求管理员权限失败 (Code {ret})")
        except Exception as e:
            self.log(f"Elevation failed: {e}")

if __name__ == "__main__":
    try:
        app = App()
        app.protocol("WM_DELETE_WINDOW", app.on_closing)
        app.mainloop()
    except Exception as e:
        # Show error in a popup window since console might not be available
        try:
            import tkinter.messagebox
            tkinter.messagebox.showerror("Startup Error", f"An error occurred during startup:\n{e}")
        except:
            pass
        # Also write to a log file
        with open("error_log.txt", "w") as f:
            import traceback
            traceback.print_exc(file=f)
