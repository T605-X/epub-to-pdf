#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EPUB 转 PDF Web 转换器 - 使用 WeasyPrint"""

import os
import sys
import uuid
import re
import io
import tempfile
from pathlib import Path
from flask import Flask, render_template, request, send_file, jsonify, Response
from werkzeug.utils import secure_filename
import threading

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
from weasyprint import HTML, CSS

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')
os.makedirs(OUTPUT_DIR, exist_ok=True)

tasks = {}


class ConversionTask:
    def __init__(self, task_id):
        self.task_id = task_id
        self.status = 'pending'
        self.progress = 0
        self.message = '等待中...'
        self.input_path = None
        self.output_path = None
        self.output_bytes = None
        self.original_filename = None
        self.error = None

    def update_progress(self, message):
        self.message = message
        if '%' in message:
            try:
                self.progress = int(message.split('%')[0].split('...')[-1].strip())
            except:
                pass


class EpubToPdfConverter:

    def __init__(self, progress_callback=None):
        self.progress_callback = progress_callback
        self.pdf_bytes = None

    def log(self, message):
        print(f"[CONVERTER] {message}")
        if self.progress_callback:
            self.progress_callback(message)

    def convert(self, epub_path, pdf_path):
        try:
            self.log("开始读取 EPUB 文件...")
            book = epub.read_epub(epub_path)

            # 收集所有 HTML 内容
            html_parts = []
            html_parts.append("""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <style>
                    body { font-family: Arial, sans-serif; margin: 40px; line-height: 1.6; }
                    h1 { font-size: 24px; margin-top: 30px; }
                    h2 { font-size: 20px; margin-top: 25px; }
                    h3 { font-size: 16px; margin-top: 20px; }
                    p { margin: 10px 0; text-align: justify; }
                    .page-break { page-break-after: always; }
                </style>
            </head>
            <body>
            """)

            docs = list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))

            chapter_docs = []
            for chapter_doc in docs:
                name = chapter_doc.get_name()
                if any(x in name.lower() for x in ['cover', 'toc', 'juan', 'catalog']):
                    continue
                if re.match(r'.*\d+\.html?$', name):
                    chapter_docs.append(chapter_doc)

            total_docs = len(chapter_docs)
            self.log(f"找到 {total_docs} 个章节")

            for idx, chapter_doc in enumerate(chapter_docs):
                progress = int((idx / total_docs) * 100) if total_docs > 0 else 0
                self.log(f"处理中... {progress}%")

                try:
                    content = chapter_doc.get_content().decode('utf-8', errors='ignore')
                    soup = BeautifulSoup(content, 'html.parser')

                    # 移除脚本和样式标签
                    for script in soup(["script", "style"]):
                        script.decompose()

                    body = soup.find('body')
                    if body:
                        html_parts.append(str(body))
                        html_parts.append('<div class="page-break"></div>')

                except Exception as e:
                    self.log(f"处理文档出错: {e}")
                    continue

            html_parts.append("</body></html>")
            full_html = "\n".join(html_parts)

            self.log("正在生成 PDF...")

            # 使用 WeasyPrint 生成 PDF
            html_obj = HTML(string=full_html)
            pdf_buffer = io.BytesIO()
            html_obj.write_pdf(pdf_buffer)
            pdf_buffer.seek(0)
            self.pdf_bytes = pdf_buffer.read()

            self.log(f"转换完成！PDF 大小: {len(self.pdf_bytes)} 字节")
            return True

        except Exception as e:
            self.log(f"转换失败: {str(e)}")
            import traceback
            traceback.print_exc()
            raise


def convert_file(task_id):
    task = tasks[task_id]
    try:
        task.status = 'processing'
        converter = EpubToPdfConverter(progress_callback=task.update_progress)
        success = converter.convert(task.input_path, task.output_path)

        if success and converter.pdf_bytes and len(converter.pdf_bytes) > 100:
            task.status = 'completed'
            task.progress = 100
            task.output_bytes = converter.pdf_bytes
        else:
            task.status = 'failed'
            task.error = '转换失败：PDF 生成失败或文件太小'

    except Exception as e:
        print(f"[ERROR] 转换异常: {str(e)}")
        import traceback
        traceback.print_exc()
        task.status = 'failed'
        task.error = str(e)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
def upload():
    try:
        print("[UPLOAD] 收到上传请求")

        if 'file' not in request.files:
            return jsonify({'error': '没有选择文件'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': '请选择文件'}), 400

        if not file.filename.lower().endswith('.epub'):
            return jsonify({'error': '只支持 EPUB 格式文件'}), 400

        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)

        print(f"[UPLOAD] 文件大小: {file_size} 字节")

        if file_size == 0:
            return jsonify({'error': '文件大小为0，请重新选择文件'}), 400

        if file_size > 50 * 1024 * 1024:
            return jsonify({'error': '文件大小不能超过50MB'}), 400

        task_id = str(uuid.uuid4())
        task = ConversionTask(task_id)
        tasks[task_id] = task

        input_path = os.path.join(OUTPUT_DIR, f"{task_id}_{secure_filename(file.filename)}")
        file.save(input_path)

        print(f"[UPLOAD] 文件保存到: {input_path}")

        if not os.path.exists(input_path) or os.path.getsize(input_path) == 0:
            return jsonify({'error': '文件保存失败，请重试'}), 500

        task.input_path = input_path
        task.output_path = os.path.join(OUTPUT_DIR, f"{task_id}.pdf")
        task.original_filename = file.filename

        thread = threading.Thread(target=convert_file, args=(task_id,))
        thread.daemon = True
        thread.start()

        print(f"[UPLOAD] 任务 {task_id} 已启动")
        return jsonify({'task_id': task_id, 'status': 'processing'})

    except Exception as e:
        print(f"[UPLOAD ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'上传失败: {str(e)}'}), 500


@app.route('/status/<task_id>')
def get_status(task_id):
    if task_id not in tasks:
        return jsonify({'error': '任务不存在'}), 404

    task = tasks[task_id]
    return jsonify({
        'task_id': task_id,
        'status': task.status,
        'progress': task.progress,
        'message': task.message,
        'error': task.error
    })


@app.route('/download/<task_id>')
def download(task_id):
    if task_id not in tasks:
        return jsonify({'error': '任务不存在'}), 404

    task = tasks[task_id]

    if task.status != 'completed':
        return jsonify({'error': '转换尚未完成'}), 400

    if not task.output_bytes or len(task.output_bytes) < 100:
        return jsonify({'error': 'PDF 文件生成失败'}), 400

    pdf_name = task.original_filename.replace('.epub', '.pdf') if task.original_filename else 'output.pdf'

    print(f"[DOWNLOAD] 下载 PDF，大小: {len(task.output_bytes)} 字节")

    response = Response(
        task.output_bytes,
        mimetype='application/pdf',
        headers={
            'Content-Disposition': f'attachment; filename="{pdf_name}"',
            'Content-Length': str(len(task.output_bytes)),
        }
    )
    return response


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
