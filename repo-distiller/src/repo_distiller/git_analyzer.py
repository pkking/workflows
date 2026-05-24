import pygit2
from pathlib import Path
from typing import Dict, List
from collections import defaultdict


class GitAnalyzer:

    def __init__(self, repo_path: Path):
        self.repo = pygit2.Repository(str(repo_path))

    def analyze(self, limit: int = 500) -> Dict:
        head_target = None
        try:
            head_target = self.repo.head.target
        except pygit2.GitError:
            refs = self.repo.listall_references()
            for ref in refs:
                if ref.startswith("refs/heads/") or ref.startswith("refs/remotes/"):
                    try:
                        head_target = self.repo.lookup_reference(ref).target
                        break
                    except:
                        pass
                        
        if not head_target:
            return {"commits": [], "hotspots": [], "couplings": []}
            
        walker = self.repo.walk(head_target, pygit2.GIT_SORT_TIME)
        
        commits = []
        file_churn = defaultdict(int)
        co_changes = defaultdict(lambda: defaultdict(int))
        
        count = 0
        for commit in walker:
            if count >= limit:
                break
            if len(commit.parents) > 1:
                count += 1
                continue
                
            parent = commit.parents[0] if commit.parents else None
            if parent:
                diff = self.repo.diff(parent, commit)
            else:
                diff = commit.tree.diff_to_tree(swap=True)
            stats = diff.stats
            
            files_changed = set()
            for patch in diff:
                if patch.delta.old_file.path: files_changed.add(patch.delta.old_file.path)
                if patch.delta.new_file.path: files_changed.add(patch.delta.new_file.path)
            
            files_list = list(files_changed)
            msg = commit.message.lower()
            is_fix = any(k in msg for k in ["fix", "bug", "issue", "revert", "patch"])
            is_large = stats.insertions > 100 or stats.deletions > 100
            
            commits.append({
                "hash": str(commit.id)[:8],
                "author": commit.author.name,
                "message": commit.message.strip()[:100],
                "files": files_list,
                "insertions": stats.insertions,
                "deletions": stats.deletions,
                "is_fix": is_fix,
                "is_large": is_large,
            })
            
            for f in files_list:
                file_churn[f] += 1
                for other in files_list:
                    if f != other:
                        co_changes[f][other] += 1
            
            count += 1
            
        hotspots = sorted(file_churn.items(), key=lambda x: x[1], reverse=True)[:10]
        
        couplings = []
        for f1, others in co_changes.items():
            for f2, count in others.items():
                if count > 3:
                    couplings.append({"file1": f1, "file2": f2, "count": count})
        couplings.sort(key=lambda x: x["count"], reverse=True)
        
        return {
            "commits": commits,
            "hotspots": [{"file": f, "churn": c} for f, c in hotspots],
            "couplings": couplings[:10],
        }
