"""总结模块 - 通过OpenAI兼容API对转写文本进行总结"""

import json
import os
from config import load_config


class Summarizer:
    """调用OpenAI兼容API进行文本总结"""

    def __init__(self):
        self.cfg = load_config()

    def _get_client(self):
        from openai import OpenAI
        return OpenAI(
            api_key=self.cfg.get("api_key", "sk-"),
            base_url=self.cfg.get("api_base_url", "https://api.openai.com/v1"),
        )

    def summarize(self, text, custom_prompt=None, progress_callback=None):
        """对文本进行总结"""
        client = self._get_client()
        model = self.cfg.get("api_model", "gpt-4o")

        prompt = custom_prompt or (
            "你是一个专业的课程内容总结助手。请对以下课程转录文字进行总结，"
            "要求：\n"
            "1. 提炼课程的核心主题和关键知识点\n"
            "2. 按主题分段，每段有清晰的小标题\n"
            "3. 不要遗漏重要的概念、公式、案例\n"
            "4. 用中文输出\n\n"
            f"课程转录内容：\n{text}"
        )

        # 如果文本过长，分段处理
        if len(text) > 8000:
            return self._summarize_long_text(client, model, text, prompt,
                                             progress_callback)

        if progress_callback:
            progress_callback(0.3)

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是一个专业的课程笔记整理助手，擅长提炼和总结知识点。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=4096,
        )

        if progress_callback:
            progress_callback(1.0)

        return response.choices[0].message.content

    def _summarize_long_text(self, client, model, text, base_prompt,
                             progress_callback=None):
        """分段总结长文本"""
        chunk_size = 6000
        chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
        summaries = []

        for i, chunk in enumerate(chunks):
            if progress_callback:
                progress_callback((i / len(chunks)) * 0.6)

            prompt = (
                f"这是课程转录的第{i+1}/{len(chunks)}部分。请总结这部分的要点：\n\n{chunk}"
            )
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=2048,
            )
            summaries.append(resp.choices[0].message.content)

        if len(summaries) == 1:
            return summaries[0]

        if progress_callback:
            progress_callback(0.7)

        merged = "\n\n".join(
            f"第{i+1}部分要点：\n{s}" for i, s in enumerate(summaries)
        )
        final_prompt = (
            "请将以下多段课程要点合并为一份完整的课程总结，去除重复内容，"
            "按逻辑结构重新组织：\n\n" + merged
        )
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": final_prompt}],
            temperature=0.3,
            max_tokens=4096,
        )

        if progress_callback:
            progress_callback(1.0)

        return resp.choices[0].message.content

    def save_summary(self, summary_text, output_path):
        """保存总结到文件"""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(summary_text)
        return output_path
