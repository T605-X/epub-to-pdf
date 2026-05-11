#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EPUB 转 PDF Web 转换器 - 保留原始格式
"""

import os
import sys
import uuid
import re
import tempfile
from pathlib import Path
from flask import Flask, render_template, request, send_file, jsonify
from werkzeug.utils import secure_filename
import threading

# EPUB 处理
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup

# PDF 生成
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = tempfile.gettempdir()

tasks = {}


class ConversionTask:
    def __init__(self, task_id):
        self.task_id = task_id
        self.status = 'pending'
        self.progress = 0
        self.message = '等待中...'
        self.input_path = None
        self.output_path = None
        self.error = None
    
    def update_progress(self, message):
        self.message = message
        if '%' in message:
            try:
                self.progress = int(message.split('%')[0].split('...')[-1].strip())
            except:
                pass


class EpubToPdfConverter:
    """EPUB 转 PDF 转换器 - 保留原始格式"""
    
    def __init__(self, progress_callback=None):
        self.progress_callback = progress_callback
        self.styles = None
        self.register_fonts()
    
    def register_fonts(self):
        """注册中文字体"""
        font_paths = [
            ("WenQuanYi", "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
            ("WenQuanYi", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
            ("NotoSansCJK", "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
        ]
        
        self.chinese_font_name = "Helvetica"
        for font_name, font_path in font_paths:
            if os.path.exists(font_path):
                try:
                    pdfmetrics.registerFont(TTFont(font_name, font_path))
                    self.chinese_font_name = font_name
                    break
                except:
                    continue
    
    def log(self, message):
        if self.progress_callback:
            self.progress_callback(message)
    
    def parse_css_style(self, style_str):
        """解析 CSS 样式字符串"""
        styles = {}
        if not style_str:
            return styles
        
        # 解析 font-size
        size_match = re.search(r'font-size:\s*(\d+)\s*px', style_str)
        if size_match:
            styles['font_size'] = int(size_match.group(1))
        
        # 解析 line-height
        lh_match = re.search(r'line-height:\s*(\d+\.?\d*)', style_str)
        if lh_match:
            styles['line_height'] = float(lh_match.group(1))
        
        # 解析 text-align
        if 'text-align: center' in style_str:
            styles['alignment'] = TA_CENTER
        elif 'text-align: right' in style_str:
            styles['alignment'] = TA_RIGHT
        else:
            styles['alignment'] = TA_LEFT
        
        # 解析 font-weight
        if 'font-weight: bold' in style_str or 'font-weight: 700' in style_str:
            styles['bold'] = True
        
        return styles
    
    def convert(self, epub_path, pdf_path):
        """转换 EPUB 到 PDF"""
        try:
            self.log(f"开始读取 EPUB 文件...")
            book = epub.read_epub(epub_path)
            
            # 创建 PDF
            pdf_doc = SimpleDocTemplate(
                pdf_path,
                pagesize=A4,
                rightMargin=72,
                leftMargin=72,
                topMargin=72,
                bottomMargin=72
            )
            
            story = []
            docs = list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))
            
            # 过滤有效文档
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
                    soup = BeautifulSoup(chapter_doc.get_content(), 'html.parser')
                    
                    # 移除脚本和样式标签
                    for script in soup(["script", "style"]):
                        script.decompose()
                    
                    body = soup.find('body')
                    if not body:
                        continue
                    
                    # 处理所有元素
                    for elem in body.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'div', 'span']):
                        text = elem.get_text(strip=True)
                        if not text:
                            continue
                        
                        # 获取样式
                        style = elem.get('style', '')
                        css_styles = self.parse_css_style(style)
                        
                        # 根据标签类型设置默认样式
                        if elem.name == 'h1':
                            font_size = css_styles.get('font_size', 24)
                            para = Paragraph(text, self.create_style(font_size, bold=True))
                        elif elem.name == 'h2':
                            font_size = css_styles.get('font_size', 20)
                            para = Paragraph(text, self.create_style(font_size, bold=True))
                        elif elem.name in ['h3', 'h4', 'h5', 'h6']:
                            font_size = css_styles.get('font_size', 16)
                            para = Paragraph(text, self.create_style(font_size, bold=True))
                        else:
                            # 段落 - 使用原始字号或默认11pt
                            font_size = css_styles.get('font_size', 11)
                            line_height = css_styles.get('line_height', 1.6)
                            para = Paragraph(text, self.create_style(font_size, line_height=line_height))
                        
                        story.append(para)
                        story.append(Spacer(1, 6))
                    
                    # 章节分页
                    story.append(PageBreak())
                    
                except Exception as e:
                    self.log(f"处理文档出错: {e}")
                    continue
            
            self.log("正在生成 PDF...")
            pdf_doc.build(story)
            self.log("转换完成！")
            return True
            
        except Exception as e:
            self.log(f"转换失败: {str(e)}")
            raise
    
    def create_style(self, font_size=11, bold=False, line_height=1.6, alignment=TA_LEFT):
        """创建段落样式"""
        style_name = f'Custom_{font_size}_{bold}_{line_height}'
        
        leading = font_size * line_height
        
        return ParagraphStyle(
            name=style_name,
            fontName=self.chinese_font_name,
            fontSize=font_size,
            leading=leading,
            alignment=alignment,
            spaceBefore=6,
            spaceAfter=6,
            firstLineIndent=22 if not bold else 0,
        )


def convert_file(task_id):
    """后台转换"""
    task = tasks[task_id]
    
    try:
        task.status = 'processing'
        converter = EpubToPdfConverter(progress_callback=task.update_progress)
        success = converter.convert(task.input_path, task.output_path)
        
        if success:
            task.status = 'completed'
            task.progress = 100
        else:
            task.status = 'failed'
            task.error = '转换失败'
            
    except Exception as e:
        task.status = 'failed'
        task.error = str(e)
    
    # 清理输入文件
    try:
        if os.path.exists(task.input_path):
            os.remove(task.input_path)
    except:
        pass


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
def upload():
    try:
        if 'file' not in request.files:
            return jsonify({'error': '没有选择文件'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': '请选择文件'}), 400
        
        if not file.filename.lower().endswith('.epub'):
            return jsonify({'error': '只支持 EPUB 格式文件'}), 400
        
        # 检查文件大小
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)
        
        if file_size == 0:
            return jsonify({'error': '文件大小为0，请重新选择文件'}), 400
        
        if file_size > 50 * 1024 * 1024:  # 限制50MB
            return jsonify({'error': '文件大小不能超过50MB'}), 400
        
        task_id = str(uuid.uuid4())
        task = ConversionTask(task_id)
        tasks[task_id] = task
        
        # 确保上传目录存在
        upload_folder = app.config['UPLOAD_FOLDER']
        os.makedirs(upload_folder, exist_ok=True)
        
        input_path = os.path.join(upload_folder, f"{task_id}_{secure_filename(file.filename)}")
        file.save(input_path)
        
        # 验证文件是否保存成功
        if not os.path.exists(input_path) or os.path.getsize(input_path) == 0:
            return jsonify({'error': '文件保存失败，请重试'}), 500
        
        task.input_path = input_path
        task.output_path = os.path.join(upload_folder, f"{task_id}.pdf")
        
        thread = threading.Thread(target=convert_file, args=(task_id,))
        thread.daemon = True
        thread.start()
        
        return jsonify({'task_id': task_id, 'status': 'processing'})
        
    except Exception as e:
        print(f"上传错误: {str(e)}")
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
    
    if not os.path.exists(task.output_path):
        return jsonify({'error': '文件不存在'}), 404
    
    original_name = os.path.basename(task.input_path)
    if '_' in original_name:
        original_name = original_name.split('_', 1)[1]
    original_name = original_name.replace('.epub', '.pdf')
    
    return send_file(
        task.output_path,
        as_attachment=True,
        download_name=original_name,
        mimetype='application/pdf'
    )


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
