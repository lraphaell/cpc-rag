# 🚀 Quick Start: Local Files (No Google API Needed!)

**Perfect for:** Getting started immediately without Google Drive API setup

---

## ⚡ 3-Step Quick Start

### Step 1: Set Up Pinecone (2 minutes)

```bash
# Edit .env file
nano .env

# Add your Pinecone credentials:
PINECONE_API_KEY=your_actual_api_key
PINECONE_ENVIRONMENT=your_environment
PINECONE_INDEX_NAME=your_index_name
```

Get these from: https://app.pinecone.io/

### Step 2: Start MCP Server (1 minute)

```bash
# Install MCP server (one-time)
python3 -m pip install --user pipx
pipx install mcp-remote-proxy --index-url "https://pypi.artifacts.furycloud.io/simple/" --python 3.11

# Start server (keep this terminal open)
mcp-remote-proxy --host localhost --port 8080 --backend pinecone
```

### Step 3: Process Your Documents! (5 minutes)

```bash
# Point to your documents folder (use your actual path)
cd "/Users/lraphael/Documents/Agents - IA - Cloude - Scripts/Data Cleanup for RAG Agent"

python3 tools/create_local_manifest.py \
  --source_dir "~/Library/CloudStorage/GoogleDrive-lucas.raphael@mercadopago.com.br/Meu Drive/YOUR_FOLDER_NAME" \
  --output_dir ".tmp/my_first_run/downloads/"
```

Then tell me:
```
"Analyze the files in .tmp/my_first_run/file_manifest.json and run the full RAG pipeline"
```

I'll handle the rest! 🎯

---

## 📁 Your Google Drive Location

```
~/Library/CloudStorage/GoogleDrive-lucas.raphael@mercadopago.com.br/Meu Drive/
```

Any folder under "Meu Drive" works!

---

## 🎯 What You'll Get

1. **Complete file analysis** - Per-file RAG strategy recommendations
2. **Processed chunks** - Documents chunked and ingested to Pinecone
3. **Google Sheets report** - Summary with success rates, errors, statistics

---

## 📝 Supported File Types

✅ PDF (.pdf)
✅ Word (.docx, .doc)
✅ PowerPoint (.pptx, .ppt)
✅ Excel (.xlsx, .xls)
✅ CSV (.csv)
✅ Text (.txt, .md)

---

## 🔍 Example: Test with Sample Files

```bash
# 1. Create test folder with 3-5 documents
mkdir -p ~/Desktop/RAG_Test
# Copy some PDFs, Word docs, etc. to this folder

# 2. Run pipeline
python3 tools/create_local_manifest.py \
  --source_dir ~/Desktop/RAG_Test \
  --output_dir ".tmp/test/downloads/"

# 3. Then ask me: "Process .tmp/test/file_manifest.json through RAG pipeline"
```

---

## ❓ FAQ

**Q: Do I need Google Drive API?**
A: No! If Google Drive desktop app is installed, you're all set.

**Q: Will this work with any local folder?**
A: Yes! Works with any folder containing documents, not just Google Drive.

**Q: What if I don't have Google Drive installed?**
A: No problem - works with any local folder on your Mac.

**Q: Do I need internet?**
A: Only for Pinecone ingestion. File reading is all local.

**Q: Can I test without Pinecone?**
A: You can run create_local_manifest.py and see the file analysis, but ingestion requires Pinecone.

---

## ✅ Checklist

- [ ] Add Pinecone credentials to `.env`
- [ ] Install and start MCP server
- [ ] Choose a folder with documents
- [ ] Run `create_local_manifest.py`
- [ ] Ask me to process the manifest!

**Total time: ~10 minutes**

---

## 🆘 Need Help?

Just ask me:
- "Show me what folders I have in Google Drive"
- "Create a test run with files from [folder path]"
- "Troubleshoot my MCP connection"
- "Generate a sample workflow"

**Ready to process your first documents?** 🚀
