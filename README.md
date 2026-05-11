# EPUB 转 PDF 在线转换器

一个简洁好用的在线 EPUB 转 PDF 转换工具，支持拖拽上传，保留原始格式。

## 功能特点

- 📁 拖拽上传 EPUB 文件
- 📊 实时转换进度显示
- ✅ 保留原始字号和行间距
- 🔤 支持中文字体
- 📱 响应式设计，手机电脑都能用

## 部署到 Render

1. 创建 GitHub 仓库，上传所有文件
2. 访问 https://render.com/
3. 用 GitHub 登录
4. 点击 **New +** → **Web Service**
5. 选择此仓库
6. 配置：
   - Name: `epub-to-pdf`
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn app:app --bind 0.0.0.0:$PORT`
7. 点击 **Create Web Service**
8. 等待部署完成，获得公共链接

## 本地运行

```bash
pip install -r requirements.txt
python app.py
```

然后访问 http://localhost:5000

## 技术栈

- Flask - Web 框架
- ReportLab - PDF 生成
- EbookLib - EPUB 解析
- BeautifulSoup - HTML 解析
