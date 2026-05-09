"""语义记忆 — 跨 Session 的长期知识存储与检索。

基于关键词索引 + 文件持久化，零外部依赖。
支持跨 session 的知识沉淀和相似度检索。
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from harness.core.memory.base import BaseMemory, Summary
from harness.core.types import LLMMessage


@dataclass
class KnowledgeEntry:
    """知识条目。"""
    id: str
    content: str
    source_session: str
    created_at: datetime = field(default_factory=datetime.now)
    access_count: int = 0
    tags: list[str] = field(default_factory=list)
    keywords: dict[str, float] = field(default_factory=dict)


class SemanticMemory(BaseMemory):
    """语义记忆 — 跨 Session 的长期知识存储与检索。

    使用 TF-IDF 风格的词频-重要性评分进行检索。
    知识条目持久化到 JSON 文件，支持增量更新。
    """

    def __init__(self, persist_dir: str = ".harness/memory/semantic"):
        self.persist_dir = Path(persist_dir)
        self._entries: list[KnowledgeEntry] = []
        self._id_counter = 0
        self._load()

    async def add(self, message: LLMMessage) -> None:
        """存储一条消息到语义记忆。"""
        if not message.content or len(message.content) < 20:
            return

        keywords = self._extract_keywords(message.content)
        entry = KnowledgeEntry(
            id=f"k_{self._id_counter}",
            content=message.content[:1000],
            source_session="current",
            keywords=keywords,
            tags=self._extract_tags(message.content),
        )
        self._id_counter += 1
        self._entries.append(entry)

    async def add_knowledge(
        self,
        content: str,
        source_session: str = "",
        tags: list[str] | None = None,
    ) -> None:
        """添加一条知识条目。"""
        if not content:
            return
        keywords = self._extract_keywords(content)
        entry = KnowledgeEntry(
            id=f"k_{self._id_counter}",
            content=content[:2000],
            source_session=source_session or "unknown",
            keywords=keywords,
            tags=tags or [],
        )
        self._id_counter += 1
        self._entries.append(entry)
        self._save()

    async def get_context(self, limit: int = 5) -> list[LLMMessage]:
        """获取最近最常访问的知识作为上下文。"""
        sorted_entries = sorted(
            self._entries,
            key=lambda e: (e.access_count, e.created_at.timestamp()),
            reverse=True,
        )
        messages = []
        for entry in sorted_entries[:limit]:
            messages.append(LLMMessage(
                role="system",
                content=f"[Long-term knowledge]: {entry.content[:500]}",
            ))
        return messages

    async def search(self, query: str, top_k: int = 5) -> list[KnowledgeEntry]:
        """搜索语义记忆 — 基于 TF-IDF 关键词匹配。

        Args:
            query: 搜索查询
            top_k: 返回结果数量

        Returns:
            list[KnowledgeEntry]: 匹配的知识条目
        """
        if not self._entries:
            return []

        query_keywords = self._extract_keywords(query)
        if not query_keywords:
            return []

        # 计算每个条目与查询的相关性分数
        scored = []
        for entry in self._entries:
            score = self._compute_relevance(query_keywords, entry.keywords)
            if score > 0:
                scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)

        results = [entry for _, entry in scored[:top_k]]
        # 增加访问计数
        for entry in results:
            entry.access_count += 1
        return results

    async def query(self, query: str, top_k: int = 5) -> list[str]:
        """搜索并返回内容列表。"""
        results = await self.search(query, top_k)
        return [r.content for r in results]

    async def clear(self) -> None:
        self._entries.clear()
        self._id_counter = 0
        self._save()

    async def count_tokens(self) -> int:
        total = 0
        for e in self._entries:
            total += len(e.content)
        return total

    @property
    def count(self) -> int:
        return len(self._entries)

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息。"""
        if not self._entries:
            return {"count": 0}
        return {
            "count": len(self._entries),
            "total_chars": sum(len(e.content) for e in self._entries),
            "top_tags": Counter(
                tag for e in self._entries for tag in e.tags
            ).most_common(5),
            "most_accessed": sorted(
                [{"content": e.content[:50], "access_count": e.access_count}
                 for e in self._entries],
                key=lambda x: x["access_count"],
                reverse=True,
            )[:3],
        }

    # ---- 内部方法 ----

    def _extract_keywords(self, text: str) -> dict[str, float]:
        """从文本中提取关键词及重要性分数。"""
        # 分词
        words = re.findall(r'[a-zA-Z_]\w+|[一-龥]{2,}', text.lower())
        if not words:
            return {}

        # 停用词
        stop_words = {
            'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
            'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
            'would', 'could', 'should', 'may', 'might', 'can', 'shall',
            'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from',
            'as', 'into', 'through', 'during', 'before', 'after', 'above',
            'below', 'between', 'out', 'off', 'over', 'under', 'again',
            'further', 'then', 'once', 'here', 'there', 'when', 'where',
            'why', 'how', 'all', 'each', 'every', 'both', 'few', 'more',
            'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only',
            'own', 'same', 'so', 'than', 'too', 'very', 'just', 'because',
            'and', 'but', 'or', 'if', 'while', 'about', 'up',
        }

        # 词频
        word_counts = Counter(w for w in words if w not in stop_words and len(w) > 1)

        if not word_counts:
            return {}

        max_count = max(word_counts.values())
        total_words = len(words)

        # 计算 TF (词频) 分数
        keywords = {}
        for word, count in word_counts.most_common(20):
            tf = count / max_count  # 归一化词频
            idf = math.log((total_words + 1) / (count + 1)) + 1  # 逆向文档频率
            keywords[word] = round(tf * idf, 4)

        return keywords

    def _compute_relevance(
        self,
        query_keywords: dict[str, float],
        entry_keywords: dict[str, float],
    ) -> float:
        """计算查询与条目之间的相关性分数。"""
        if not query_keywords or not entry_keywords:
            return 0.0

        score = 0.0
        for word, q_weight in query_keywords.items():
            if word in entry_keywords:
                score += q_weight * entry_keywords[word]

        # 归一化
        max_possible = sum(qw * max(entry_keywords.values() or [1])
                          for qw in query_keywords.values())
        if max_possible == 0:
            return 0.0
        return score / max_possible

    def _extract_tags(self, text: str) -> list[str]:
        """从文本中提取标签。"""
        tags = []
        # 检测 #tag 格式
        tags.extend(re.findall(r'#(\w+)', text))
        # 检测关键词
        topic_words = ['code', 'bug', 'feature', 'config', 'deploy',
                       'test', 'api', 'database', 'security', 'performance']
        text_lower = text.lower()
        for word in topic_words:
            if word in text_lower:
                tags.append(word)
        return list(set(tags))

    # ---- 持久化 ----

    def _save(self) -> None:
        """保存到文件。"""
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        file_path = self.persist_dir / "knowledge.json"
        data = {
            "id_counter": self._id_counter,
            "entries": [
                {
                    "id": e.id,
                    "content": e.content,
                    "source_session": e.source_session,
                    "created_at": e.created_at.isoformat(),
                    "access_count": e.access_count,
                    "tags": e.tags,
                    "keywords": e.keywords,
                }
                for e in self._entries
            ],
        }
        file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def _load(self) -> None:
        """从文件加载。"""
        file_path = self.persist_dir / "knowledge.json"
        if not file_path.exists():
            return
        try:
            data = json.loads(file_path.read_text())
            self._id_counter = data.get("id_counter", 0)
            self._entries = [
                KnowledgeEntry(
                    id=e["id"],
                    content=e["content"],
                    source_session=e.get("source_session", ""),
                    created_at=datetime.fromisoformat(e["created_at"]),
                    access_count=e.get("access_count", 0),
                    tags=e.get("tags", []),
                    keywords=e.get("keywords", {}),
                )
                for e in data.get("entries", [])
            ]
        except (json.JSONDecodeError, KeyError, ValueError):
            self._entries = []
            self._id_counter = 0

    async def extract_and_store(
        self, session_content: list[str], session_id: str
    ) -> int:
        """从 Session 内容中提取知识并存储。

        Args:
            session_content: Session 中的文本片段列表
            session_id: 源 session ID

        Returns:
            int: 存储的知识条目数
        """
        stored = 0
        for text in session_content:
            if len(text) < 50:
                continue
            # 检测是否有值得存储的知识
            knowledge_indicators = [
                "key takeaway", "important", "remember", "note:",
                "关键", "注意", "总结", "规律", "模式",
            ]
            if any(ind in text.lower() for ind in knowledge_indicators):
                await self.add_knowledge(
                    content=text,
                    source_session=session_id,
                    tags=self._extract_tags(text),
                )
                stored += 1
        return stored
