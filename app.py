#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EPUB 转 PDF 转换器 - 同步版"""

import os
import re
import io
import tempfile
from flask import Flask, render_template, request, Response
from werkzeug.utils import secure_filename

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')
os.makedirs(OUTPUT_DIR, exist_ok=True)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/convert', methods=['POST'])
def convert():
    try:
        print("[CONVERT] 收到转换请求")

        if 'file' not in request.files:
            return Response("没有选择文件", status=400)

        file = request.files['file']
        if not file.filename.lower().endswith('.epub'):
            return Response("只支持 EPUB 格式", status=400)

        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)

        print(f"[CONVERT] 文件大小: {file_size}")

        if file_size == 0:
            return Response("文件为空", status=400)

        # 保存上传文件
        task_id = os.urandom(8).hex()
        input_path = os.path.join(OUTPUT_DIR, f"{task_id}.epub")
        file.save(input_path)
        print(f"[CONVERT] 文件已保存: {input_path}")

        # 读取 EPUB
        print("[CONVERT] 开始读取 EPUB...")
        book = epub.read_epub(input_path)

        # 创建 PDF 到内存
        pdf_buffer = io.BytesIO()
        pdf_doc = SimpleDocTemplate(
            pdf_buffer, pagesize=A4,
            rightMargin=72, leftMargin=72,
            topMargin=72, bottomMargin=72
        )

        story = []
        docs = list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))

        chapter_docs = []
        for d in docs:
            name = d.get_name()
            if any(x in name.lower() for x in ['cover', 'toc', 'juan', 'catalog']):
                continue
            chapter_docs.append(d)

        print(f"[CONVERT] 找到 {len(chapter_docs)} 个文档")

        for idx, d in enumerate(chapter_docs):
            try:
                content = d.get_content().decode('utf-8', errors='ignore')
                soup = BeautifulSoup(content, 'html.parser')
                for s in soup(["script", "style"]):
                    s.decompose()
                body = soup.find('body')
                if not body:
                    continue

                for elem in body.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p']):
                    text = elem.get_text(strip=True)
                    if not text or len(text) < 2:
                        continue

                    if elem.name in ['h1', 'h2']:
                        style = ParagraphStyle('h', fontName='Helvetica', fontSize=20, leading=26, spaceBefore=20, spaceAfter=10)
                    elif elem.name in ['h3', 'h4', 'h5', 'h6']:
                        style = ParagraphStyle('h3', fontName='Helvetica', fontSize=16, leading=22, spaceBefore=15, spaceAfter=8)
                    else:
                        style = ParagraphStyle('p', fontName='Helvetica', fontSize=11, leading=18, spaceBefore=4, spaceAfter=4, firstLineIndent=22)

                    story.append(Paragraph(text, style))
                    story.append(Spacer(1, 4))

                story.append(PageBreak())
            except Exception as e:
                print(f"[CONVERT] 处理文档出错: {e}")
                continue

        print(f"[CONVERT] 共添加 {len(story)} 个元素，开始生成 PDF...")

        # 生成 PDF
        pdf_doc.build(story)

        # 读取 PDF 数据
        pdf_buffer.seek(0)
        pdf_bytes = pdf_buffer.read()
        pdf_size = len(pdf_bytes)

        print(f"[CONVERT] PDF 生成完成！大小: {pdf_size} 字节")

        # 清理
        try:
            os.remove(input_path)
        except:
            pass

        if pdf_size < 100:
            return Response("PDF 生成失败", status=500)

        # 返回 PDF
        pdf_name = file.filename.replace('.epub', '.pdf')
        return Response(
            pdf_bytes,
            mimetype='application/pdf',
            headers={
                'Content-Disposition': f'attachment; filename="{pdf_name}"',
                'Content-Length': str(pdf_size),
            }
        )

    except Exception as e:
        print(f"[CONVERT ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        return Response(f"转换失败: {str(e)}", status=500)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
