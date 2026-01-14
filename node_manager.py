import os
import git
import json
import shutil
import datetime
from typing import List, Optional, Dict
from dataclasses import dataclass

# Use absolute path for metadata file to avoid issues with CWD
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
META_FILE = os.path.join(BASE_DIR, "nodes_meta.json")

@dataclass
class Node:
    name: str
    path: str
    is_git_repo: bool
    remote_url: Optional[str] = None
    last_update_time: Optional[str] = None
    install_time: Optional[str] = None
    
    def __repr__(self):
        return f"Node(name='{self.name}', is_git={self.is_git_repo}, url='{self.remote_url}', last_update='{self.last_update_time}', install_time='{self.install_time}')"

class NodeManager:
    def __init__(self):
        self.metadata = self.load_metadata()

    def load_metadata(self) -> Dict[str, Dict]:
        if os.path.exists(META_FILE):
            try:
                with open(META_FILE, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading metadata: {e}")
        return {}

    def save_metadata(self):
        try:
            with open(META_FILE, 'w') as f:
                json.dump(self.metadata, f, indent=4)
        except Exception as e:
            print(f"Error saving metadata: {e}")

    def remove_node_metadata(self, node_name: str) -> None:
        if node_name in self.metadata:
            try:
                del self.metadata[node_name]
                self.save_metadata()
            except Exception as e:
                print(f"Error removing metadata for {node_name}: {e}")

    def update_node_timestamp(self, node_path: str):
        node_name = os.path.basename(node_path)
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if node_name not in self.metadata:
            self.metadata[node_name] = {}
        
        self.metadata[node_name]["last_updated"] = now
        self.save_metadata()
        return now

    def set_node_install_time(self, node_name: str):
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if node_name not in self.metadata:
            self.metadata[node_name] = {}
            
        self.metadata[node_name]["install_time"] = now
        self.save_metadata()
        return now

    def set_node_git_url(self, node_name: str, url: str):
        if node_name not in self.metadata:
            self.metadata[node_name] = {}
        
        self.metadata[node_name]["git_url"] = url
        self.save_metadata()

    def get_node_git_url(self, node_name: str) -> Optional[str]:
        return self.metadata.get(node_name, {}).get("git_url")

    def _get_git_env(self, proxy: Optional[str]) -> Dict[str, str]:
        """Helper to construct environment variables for proxy."""
        env = os.environ.copy()
        if proxy:
            env['http_proxy'] = proxy
            env['https_proxy'] = proxy
            env['no_proxy'] = 'localhost,127.0.0.1'
        return env

    def scan_directory(self, path: str) -> List[Node]:
        """
        Scan the directory for ComfyUI nodes.
        Returns a list of Node objects.
        """
        if not os.path.exists(path):
            raise FileNotFoundError(f"The path {path} does not exist.")

        nodes = []
        # List all subdirectories in the given path
        for item in os.listdir(path):
            item_path = os.path.join(path, item)
            if os.path.isdir(item_path) and not item.startswith('.'):
                if item == "__pycache__":
                    continue
                # Check if it's a git repository
                is_git = False
                remote_url = None
                
                try:
                    # Check for .git directory explicitly or try initializing Repo object
                    if os.path.exists(os.path.join(item_path, '.git')):
                        repo = git.Repo(item_path)
                        is_git = True
                        try:
                            remote_url = repo.remotes.origin.url
                        except (AttributeError, IndexError):
                            # Handle cases where origin might not exist
                            pass
                except git.InvalidGitRepositoryError:
                    is_git = False
                except Exception as e:
                    print(f"Error scanning {item}: {e}")

                # If not a git repo, check metadata for manually set URL
                if not is_git:
                    manual_url = self.metadata.get(item, {}).get("git_url")
                    if manual_url:
                        remote_url = manual_url
                        # Treat as Git repo for migration purposes if URL is present
                        is_git = True 

                nodes.append(Node(
                    name=item,
                    path=item_path,
                    is_git_repo=is_git,
                    remote_url=remote_url,
                    last_update_time=self.metadata.get(item, {}).get("last_updated"),
                    install_time=self.metadata.get(item, {}).get("install_time")
                ))
        return nodes

    def get_git_url(self, node_path: str) -> Optional[str]:
        """
        Get the remote URL of a git repository at node_path.
        """
        try:
            repo = git.Repo(node_path)
            return repo.remotes.origin.url
        except (git.InvalidGitRepositoryError, AttributeError, IndexError):
            return None

    def clone_node(self, url: str, target_dir: str, proxy: Optional[str] = None) -> str:
        if os.path.exists(target_dir) and os.listdir(target_dir):
            raise FileExistsError(f"Target directory {target_dir} is not empty.")
        import subprocess
        env = os.environ.copy()
        if proxy:
            env['http_proxy'] = proxy
            env['https_proxy'] = proxy
            env['no_proxy'] = 'localhost,127.0.0.1'
        cmd = ['git', 'clone', url, target_dir]
        try:
            res = subprocess.run(cmd, env=env, check=True, capture_output=True, text=True)
            output = ""
            if res.stdout:
                output += res.stdout + "\n"
            if res.stderr:
                output += res.stderr + "\n"
            return output.strip()
        except subprocess.CalledProcessError as e:
            msg = ""
            if e.stdout:
                msg += e.stdout + "\n"
            if e.stderr:
                msg += e.stderr + "\n"
            raise Exception(msg.strip() or str(e))

    def copy_node(self, source_path: str, target_path: str) -> None:
        """
        Copy a node directory from source to target.
        """
        if os.path.exists(target_path):
             raise FileExistsError(f"Target directory {target_path} already exists.")
        
        shutil.copytree(source_path, target_path)

    def delete_node(self, node_path: str) -> None:
        if not os.path.exists(node_path):
            return
        import shutil
        import stat
        def onerror(func, path, exc_info):
            try:
                if not os.access(path, os.W_OK):
                    os.chmod(path, stat.S_IWUSR)
                func(path)
            except Exception:
                pass
        if os.path.isdir(node_path):
            shutil.rmtree(node_path, onerror=onerror)
        else:
            os.remove(node_path)


    def check_update(self, node_path: str, proxy: Optional[str] = None) -> bool:
        """
        Check if the git repository at node_path has updates.
        Returns True if updates are available, False otherwise.
        """
        try:
            repo = git.Repo(node_path)
            env = self._get_git_env(proxy)
            
            # Fetch remote with custom environment (proxy)
            # repo.remotes.origin.fetch(env=env) won't work directly because fetch takes **kwargs for flags
            # We need to use the git command wrapper for env
            
            env_args = {}
            if proxy:
                env_args['http_proxy'] = proxy
                env_args['https_proxy'] = proxy
                env_args['no_proxy'] = 'localhost,127.0.0.1'

            with repo.git.custom_environment(**env_args):
                 repo.remotes.origin.fetch()

            # Check if main/master branch is behind origin
            # This logic assumes the current branch is tracking a remote branch.
            
            if repo.head.is_detached:
                return False # Cannot check update easily for detached head without more context
            
            active_branch = repo.active_branch
            tracking_branch = active_branch.tracking_branch()
            
            if not tracking_branch:
                return False
            
            # Compare commits
            # if remote has commits that local doesn't have
            commits_behind = list(repo.iter_commits(f'{active_branch.name}..{tracking_branch.name}'))
            return len(commits_behind) > 0

        except Exception as e:
            print(f"Error checking update for {node_path}: {e}")
            return False

    def get_last_commit_info(self, node_path: str) -> str:
        """
        Get the last commit information for a node.
        Returns a formatted string with hash, author, date, and message.
        """
        try:
            repo = git.Repo(node_path)
            commit = repo.head.commit
            
            # Format time
            import datetime
            dt = datetime.datetime.fromtimestamp(commit.committed_date)
            formatted_time = dt.strftime("%Y-%m-%d %H:%M:%S")
            
            info = (
                f"Last Commit: {commit.hexsha[:7]}\n"
                f"Author: {commit.author.name}\n"
                f"Date: {formatted_time}\n"
                f"Message: {commit.message.strip()}"
            )
            return info
        except Exception as e:
            return f"Could not get commit info: {e}"

    def pull_node(self, node_path: str, proxy: Optional[str] = None) -> str:
         """
         Pull updates for a specific node.
         Returns a summary of the update (standard git pull output, including stdout and stderr).
         """
         try:
            repo = git.Repo(node_path)
            
            env_args = {}
            if proxy:
                env_args['http_proxy'] = proxy
                env_args['https_proxy'] = proxy
                env_args['no_proxy'] = 'localhost,127.0.0.1'

            with repo.git.custom_environment(**env_args):
                # Use execute to capture both stdout and stderr
                # with_extended_output=True returns (status, stdout, stderr)
                ret = repo.git.execute(['git', 'pull'], with_extended_output=True)
                _, stdout, stderr = ret
                
                # Combine stdout and stderr for full feedback
                output = ""
                if stdout:
                    output += f"{stdout}\n"
                if stderr:
                    output += f"{stderr}\n"
                
                return output.strip()
            
         except Exception as e:
             error_msg = f"Error pulling {node_path}: {e}"
             print(error_msg)
             raise Exception(error_msg)

    def install_requirements(self, node_path: str, python_path: str, proxy: Optional[str] = None) -> None:
        """
        Install requirements.txt for a node using the specified python executable.
        """
        requirements_path = os.path.join(node_path, "requirements.txt")
        if not os.path.exists(requirements_path):
            print(f"No requirements.txt found in {node_path}")
            return

        import subprocess
        
        cmd = [python_path, "-m", "pip", "install", "-r", requirements_path]
        
        env = os.environ.copy()
        if proxy:
            env['http_proxy'] = proxy
            env['https_proxy'] = proxy
            env['no_proxy'] = 'localhost,127.0.0.1'
            
        print(f"Installing requirements for {os.path.basename(node_path)}...")
        try:
            # using shell=False is safer, but on Windows with complex paths sometimes shell=True helps. 
            # Sticking to shell=False with full paths.
            subprocess.run(cmd, env=env, check=True, capture_output=True, text=True)
            print(f"Successfully installed requirements for {os.path.basename(node_path)}")
        except subprocess.CalledProcessError as e:
            print(f"Failed to install requirements for {node_path}. Error: {e.stderr}")
            raise

    def create_backup(self, nodes: List[Node], output_path: str):
        """
        Create a backup JSON file containing node names and their Git URLs.
        Only includes nodes with a valid remote_url.
        """
        backup_data = []
        for node in nodes:
            if node.remote_url and node.remote_url != "-":
                backup_data.append({
                    "name": node.name,
                    "url": node.remote_url,
                    "is_git": node.is_git_repo
                })
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(backup_data, f, indent=4, ensure_ascii=False)
        return len(backup_data)

    def load_backup(self, backup_path: str) -> List[Dict]:
        """
        Load backup data from a JSON file.
        """
        if not os.path.exists(backup_path):
            raise FileNotFoundError(f"Backup file not found: {backup_path}")
            
        with open(backup_path, 'r', encoding='utf-8') as f:
            return json.load(f)
