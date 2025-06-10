<h1 align="center">Crawl4AI RAG MCP Server</h1>

<p align="center">
  <em>Web Crawling and RAG Capabilities for AI Agents and AI Coding Assistants</em>
</p>

A powerful implementation of the [Model Context Protocol (MCP)](https://modelcontextprotocol.io) integrated with [Crawl4AI](https://crawl4ai.com) and [Supabase](https://supabase.com/) for providing AI agents and AI coding assistants with advanced web crawling and RAG capabilities.

With this MCP server, you can <b>scrape anything</b> and then <b>use that knowledge anywhere</b> for RAG.

The primary goal is to bring this MCP server into [Archon](https://github.com/coleam00/Archon) as I evolve it to be more of a knowledge engine for AI coding assistants to build AI agents. This first version of the Crawl4AI/RAG MCP server will be improved upon greatly soon, especially making it more configurable so you can use different embedding models and run everything locally with Ollama.

## Overview

This MCP server provides tools that enable AI agents to crawl websites, store content in a vector database (Supabase), and perform RAG over the crawled content. It follows the best practices for building MCP servers based on the [Mem0 MCP server template](https://github.com/coleam00/mcp-mem0/) I provided on my channel previously.

The server includes several advanced RAG strategies that can be enabled to enhance retrieval quality:
- **Contextual Embeddings** for enriched semantic understanding
- **Hybrid Search** combining vector and keyword search
- **Agentic RAG** for specialized code example extraction
- **Reranking** for improved result relevance using cross-encoder models

See the [Configuration section](#configuration) below for details on how to enable and configure these strategies.

## Vision

The Crawl4AI RAG MCP server is just the beginning. Here's where we're headed:

1. **Integration with Archon**: Building this system directly into [Archon](https://github.com/coleam00/Archon) to create a comprehensive knowledge engine for AI coding assistants to build better AI agents.

2. **Multiple Embedding Models**: Expanding beyond OpenAI to support a variety of embedding models, including the ability to run everything locally with Ollama for complete control and privacy.

3. **Advanced RAG Strategies**: Implementing sophisticated retrieval techniques like contextual retrieval, late chunking, and others to move beyond basic "naive lookups" and significantly enhance the power and precision of the RAG system, especially as it integrates with Archon.

4. **Enhanced Chunking Strategy**: Implementing a Context 7-inspired chunking approach that focuses on examples and creates distinct, semantically meaningful sections for each chunk, improving retrieval precision.

5. **Performance Optimization**: Increasing crawling and indexing speed to make it more realistic to "quickly" index new documentation to then leverage it within the same prompt in an AI coding assistant.

## Features

- **Smart URL Detection**: Automatically detects and handles different URL types (regular webpages, sitemaps, text files)
- **Recursive Crawling**: Follows internal links to discover content
- **Parallel Processing**: Efficiently crawls multiple pages simultaneously
- **Content Chunking**: Intelligently splits content by headers and size for better processing
- **Vector Search**: Performs RAG over crawled content, optionally filtering by data source for precision
- **Source Retrieval**: Retrieve sources available for filtering to guide the RAG process
- **Human-in-the-Loop (HITL) via VNC**: Allows manual browser interaction for complex scenarios (logins, CAPTCHAs) by providing a VNC session accessible via a web browser (noVNC).

## Tools

The server provides essential web crawling and search tools:

### Core Tools (Always Available)

1. **`crawl_single_page`**: Quickly crawl a single web page and store its content in the vector database
2. **`smart_crawl_url`**: Intelligently crawl a full website based on the type of URL provided (sitemap, llms-full.txt, or a regular webpage that needs to be crawled recursively)
3. **`get_available_sources`**: Get a list of all available sources (domains) in the database
4. **`perform_rag_query`**: Search for relevant content using semantic search with optional source filtering

### Conditional Tools

5. **`search_code_examples`** (requires `USE_AGENTIC_RAG=true`): Search specifically for code examples and their summaries from crawled documentation. This tool provides targeted code snippet retrieval for AI coding assistants.

### HITL Tools

6. **`initiate_human_in_the_loop(url: str)`**: Starts a browser session within a VNC-accessible virtual display. Navigates to the provided URL. Returns a session ID and a `novnc_url` to access the browser via a web interface.
7. **`resume_from_human_in_the_loop(session_id: str)`**: Signals that manual interaction in the specified HITL VNC session is complete and the session is ready for automated crawling.

**Note on HITL Usage:** The `crawl_single_page` and `smart_crawl_url` tools now accept an optional `hitl_session_id` parameter. When this parameter is provided, these tools will use the browser session initiated and managed by the HITL tools, allowing them to operate on pages that required prior manual interaction.

## Prerequisites

- [Docker/Docker Desktop](https://www.docker.com/products/docker-desktop/) if running the MCP server as a container (recommended)
- [Python 3.12+](https://www.python.org/downloads/) if running the MCP server directly through uv
- [Supabase](https://supabase.com/) (database for RAG)
- [OpenAI API key](https://platform.openai.com/api-keys) (for generating embeddings)

## Installation

### Using Docker (Recommended)

1. Clone this repository:
   ```bash
   git clone https://github.com/coleam00/mcp-crawl4ai-rag.git
   cd mcp-crawl4ai-rag
   ```

2. Build the Docker image:
   ```bash
   docker build -t mcp/crawl4ai-rag --build-arg PORT=8051 .
   ```

3. Create a `.env` file based on the configuration section below

### Using uv directly (no Docker)

1. Clone this repository:
   ```bash
   git clone https://github.com/coleam00/mcp-crawl4ai-rag.git
   cd mcp-crawl4ai-rag
   ```

2. Install uv if you don't have it:
   ```bash
   pip install uv
   ```

3. Create and activate a virtual environment:
   ```bash
   uv venv
   .venv\Scripts\activate
   # on Mac/Linux: source .venv/bin/activate
   ```

4. Install dependencies:
   ```bash
   uv pip install -e .
   crawl4ai-setup
   ```

5. Create a `.env` file based on the configuration section below

## Database Setup

Before running the server, you need to set up the database with the pgvector extension:

1. Go to the SQL Editor in your Supabase dashboard (create a new project first if necessary)

2. Create a new query and paste the contents of `crawled_pages.sql`

3. Run the query to create the necessary tables and functions

## Configuration

Create a `.env` file in the project root with the following variables:

```
# MCP Server Configuration
HOST=0.0.0.0
PORT=8051
TRANSPORT=sse

# OpenAI API Configuration
OPENAI_API_KEY=your_openai_api_key

# LLM for summaries and contextual embeddings
MODEL_CHOICE=gpt-4.1-nano

# RAG Strategies (set to "true" or "false", default to "false")
USE_CONTEXTUAL_EMBEDDINGS=false
USE_HYBRID_SEARCH=false
USE_AGENTIC_RAG=false
USE_RERANKING=false

# Supabase Configuration
SUPABASE_URL=your_supabase_project_url
SUPABASE_SERVICE_KEY=your_supabase_service_key

# HITL VNC Configuration
APP_EXTERNAL_HOSTNAME=localhost # Defaults to 'localhost'. IMPORTANT: If your Docker host is remote or accessed via a specific IP/hostname (e.g., from another machine on your network or a cloud instance), you MUST set this to that IP/hostname for the noVNC URL to be accessible.
VNC_PORT=5901      # Internal port Xvnc listens on (used by noVNC proxy)
NOVNC_PORT=6080    # External port for accessing noVNC web interface (map this port in Docker)
```

### RAG Strategy Options

The Crawl4AI RAG MCP server supports four powerful RAG strategies that can be enabled independently:

#### 1. **USE_CONTEXTUAL_EMBEDDINGS**
When enabled, this strategy enhances each chunk's embedding with additional context from the entire document. The system passes both the full document and the specific chunk to an LLM (configured via `MODEL_CHOICE`) to generate enriched context that gets embedded alongside the chunk content.

- **When to use**: Enable this when you need high-precision retrieval where context matters, such as technical documentation where terms might have different meanings in different sections.
- **Trade-offs**: Slower indexing due to LLM calls for each chunk, but significantly better retrieval accuracy.
- **Cost**: Additional LLM API calls during indexing.

#### 2. **USE_HYBRID_SEARCH**
Combines traditional keyword search with semantic vector search to provide more comprehensive results. The system performs both searches in parallel and intelligently merges results, prioritizing documents that appear in both result sets.

- **When to use**: Enable this when users might search using specific technical terms, function names, or when exact keyword matches are important alongside semantic understanding.
- **Trade-offs**: Slightly slower search queries but more robust results, especially for technical content.
- **Cost**: No additional API costs, just computational overhead.

#### 3. **USE_AGENTIC_RAG**
Enables specialized code example extraction and storage. When crawling documentation, the system identifies code blocks (≥300 characters), extracts them with surrounding context, generates summaries, and stores them in a separate vector database table specifically designed for code search.

- **When to use**: Essential for AI coding assistants that need to find specific code examples, implementation patterns, or usage examples from documentation.
- **Trade-offs**: Significantly slower crawling due to code extraction and summarization, requires more storage space.
- **Cost**: Additional LLM API calls for summarizing each code example.
- **Benefits**: Provides a dedicated `search_code_examples` tool that AI agents can use to find specific code implementations.

#### 4. **USE_RERANKING**
Applies cross-encoder reranking to search results after initial retrieval. Uses a lightweight cross-encoder model (`cross-encoder/ms-marco-MiniLM-L-6-v2`) to score each result against the original query, then reorders results by relevance.

- **When to use**: Enable this when search precision is critical and you need the most relevant results at the top. Particularly useful for complex queries where semantic similarity alone might not capture query intent.
- **Trade-offs**: Adds ~100-200ms to search queries depending on result count, but significantly improves result ordering.
- **Cost**: No additional API costs - uses a local model that runs on CPU.
- **Benefits**: Better result relevance, especially for complex queries. Works with both regular RAG search and code example search.

### Recommended Configurations

**For general documentation RAG:**
```
USE_CONTEXTUAL_EMBEDDINGS=false
USE_HYBRID_SEARCH=true
USE_AGENTIC_RAG=false
USE_RERANKING=true
```

**For AI coding assistant with code examples:**
```
USE_CONTEXTUAL_EMBEDDINGS=true
USE_HYBRID_SEARCH=true
USE_AGENTIC_RAG=true
USE_RERANKING=true
```

**For fast, basic RAG:**
```
USE_CONTEXTUAL_EMBEDDINGS=false
USE_HYBRID_SEARCH=true
USE_AGENTIC_RAG=false
USE_RERANKING=false
```

## Running the Server

### Using Docker

```bash
docker run --env-file .env \
           -e APP_EXTERNAL_HOSTNAME="your_docker_host_ip_or_hostname" \ # Set if Docker host is not 'localhost' relative to your browser
           -p 8051:8051 \
           -p 6080:6080 \
           mcp/crawl4ai-rag
```
**Note:** The `-e APP_EXTERNAL_HOSTNAME="your_docker_host_ip_or_hostname"` line is crucial if your Docker host is not `localhost` relative to your browser (e.g., if it's a remote server or a VM). If accessing from the same machine where Docker is running (and `localhost` resolves correctly to the host), you might not need to set `APP_EXTERNAL_HOSTNAME` explicitly, as it defaults to `localhost`. The port `6080` (or your configured `NOVNC_PORT`) must be accessible from your browser.

### Using Python

```bash
uv run src/crawl4ai_mcp.py
```

The server will start and listen on the configured host and port.

## Integration with MCP Clients

### SSE Configuration

Once you have the server running with SSE transport, you can connect to it using this configuration:

```json
{
  "mcpServers": {
    "crawl4ai-rag": {
      "transport": "sse",
      "url": "http://localhost:8051/sse"
    }
  }
}
```

> **Note for Windsurf users**: Use `serverUrl` instead of `url` in your configuration:
> ```json
> {
>   "mcpServers": {
>     "crawl4ai-rag": {
>       "transport": "sse",
>       "serverUrl": "http://localhost:8051/sse"
>     }
>   }
> }
> ```
>
> **Note for Docker users**: Use `host.docker.internal` instead of `localhost` if your client is running in a different container. This will apply if you are using this MCP server within n8n!

### Stdio Configuration

Add this server to your MCP configuration for Claude Desktop, Windsurf, or any other MCP client:

```json
{
  "mcpServers": {
    "crawl4ai-rag": {
      "command": "python",
      "args": ["path/to/crawl4ai-mcp/src/crawl4ai_mcp.py"],
      "env": {
        "TRANSPORT": "stdio",
        "OPENAI_API_KEY": "your_openai_api_key",
        "SUPABASE_URL": "your_supabase_url",
        "SUPABASE_SERVICE_KEY": "your_supabase_service_key"
      }
    }
  }
}
```

### Docker with Stdio Configuration

```json
{
  "mcpServers": {
    "crawl4ai-rag": {
      "command": "docker",
      "args": ["run", "--rm", "-i", 
               "-e", "TRANSPORT", 
               "-e", "OPENAI_API_KEY", 
               "-e", "SUPABASE_URL", 
               "-e", "SUPABASE_SERVICE_KEY", 
               "mcp/crawl4ai"],
      "env": {
        "TRANSPORT": "stdio",
        "OPENAI_API_KEY": "your_openai_api_key",
        "SUPABASE_URL": "your_supabase_url",
        "SUPABASE_SERVICE_KEY": "your_supabase_service_key"
      }
    }
  }
}
```

## Using Human-in-the-Loop (HITL)

The HITL feature allows you to manually interact with a web page within a browser session managed by the MCP server. This is particularly useful for handling complex logins, solving CAPTCHAs, or navigating dynamic content before automated crawling takes over. The interaction occurs within a VNC session that you can access via a noVNC URL in your web browser.

**Workflow:**

1.  **Start the MCP Server**:
    *   Ensure your Docker container is running.
    *   The `APP_EXTERNAL_HOSTNAME` environment variable defaults to `localhost`. If you are running your browser on the same machine as the Docker host (e.g., Docker Desktop), `localhost` will typically work. However, if the Docker host is remote or you access it via a specific IP or different hostname, you **must** set `APP_EXTERNAL_HOSTNAME` to that address/hostname in your `docker run` command (e.g., `-e APP_EXTERNAL_HOSTNAME="192.168.1.10"`).
    *   The `NOVNC_PORT` (default `6080`) must be mapped in your `docker run` command (e.g., `-p 6080:6080`) and be accessible from the machine where you'll open the noVNC URL.

2.  **Initiate HITL Session**:
    *   Call the `initiate_human_in_the_loop` tool, providing the initial `url` you want the browser to navigate to.
    *   Example MCP client request:
        ```json
        {
          "tool_name": "initiate_human_in_the_loop",
          "arguments": {"url": "https://example.com/login"}
        }
        ```
    *   The server will respond with a JSON object containing a `session_id` and a `novnc_url`.

3.  **Access via noVNC**:
    *   Open the `novnc_url` provided in the response (e.g., `http://localhost:6080/vnc.html` if `APP_EXTERNAL_HOSTNAME` was not set, or `http://<your_set_hostname>:6080/vnc.html` if it was) in your local web browser.
    *   You should see a browser window within the noVNC interface.

4.  **Perform Manual Interaction**:
    *   Inside the noVNC window, interact with the website displayed in the browser. This could involve:
        *   Filling out login forms.
        *   Solving CAPTCHAs.
        *   Accepting cookie banners.
        *   Navigating to a specific state or page.

5.  **Signal Completion**:
    *   Once you have completed all necessary manual steps, call the `resume_from_human_in_the_loop` tool with the `session_id` you received in Step 2.
    *   Example MCP client request:
        ```json
        {
          "tool_name": "resume_from_human_in_the_loop",
          "arguments": {"session_id": "your_session_id_here"}
        }
        ```
    *   This tells the MCP server that the browser session is now prepared for automated tools.

6.  **Use the Session for Crawling**:
    *   Call `crawl_single_page` or `smart_crawl_url` and include the `hitl_session_id` argument, using the same `session_id` from Step 2.
    *   Example MCP client request:
        ```json
        {
          "tool_name": "crawl_single_page",
          "arguments": {
            "url": "https://example.com/protected_page",
            "hitl_session_id": "your_session_id_here"
          }
        }
        ```
    *   The crawling tool will now use the browser state that you left it in after your manual interactions.

7.  **Session Cleanup**:
    *   The HITL session (including the VNC display and the browser instance) is designed for single use with a crawling tool.
    *   After the crawling tool that uses the `hitl_session_id` finishes its operation (whether it succeeds or fails), the session and its associated resources (VNC display, browser) will be automatically closed and cleaned up by the server.

**Important Note on `APP_EXTERNAL_HOSTNAME`**:
The `APP_EXTERNAL_HOSTNAME` environment variable defaults to `localhost`. This means the `novnc_url` will be like `http://localhost:6080/vnc.html`. This default works correctly if your web browser is running on the same machine as the Docker host (e.g., typical Docker Desktop setups on Windows/Mac, or when running Docker directly on Linux and browsing from the same Linux desktop).
If the Docker container is running on a remote machine, a virtual machine with a different IP, or any scenario where `localhost` in your browser would not point to the Docker host, you **must** set `APP_EXTERNAL_HOSTNAME` to the correct IP address or resolvable hostname of the Docker host when running the container (e.g., using `-e APP_EXTERNAL_HOSTNAME="192.168.1.10"`).

## Building Your Own Server

This implementation provides a foundation for building more complex MCP servers with web crawling capabilities. To build your own:

1. Add your own tools by creating methods with the `@mcp.tool()` decorator
2. Create your own lifespan function to add your own dependencies
3. Modify the `utils.py` file for any helper functions you need
4. Extend the crawling capabilities by adding more specialized crawlers