"""
MCP server for web crawling with Crawl4AI.

This server provides tools to crawl websites using Crawl4AI, automatically detecting
the appropriate crawl method based on URL type (sitemap, txt file, or regular webpage).
"""
from mcp.server.fastmcp import FastMCP, Context
from sentence_transformers import CrossEncoder
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse, urldefrag
from xml.etree import ElementTree
from dotenv import load_dotenv
from supabase import Client
from pathlib import Path
import requests
import asyncio
import json
import os
import re
import concurrent.futures
import subprocess # Added for starting fluxbox
import uuid # Added for HITL session IDs
# json is already imported earlier by `import json`
# os is already imported earlier by `import os`
from pyvirtualdisplay import Display # For virtual display management

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode, MemoryAdaptiveDispatcher

from utils import (
    get_supabase_client, 
    add_documents_to_supabase, 
    search_documents,
    extract_code_blocks,
    generate_code_example_summary,
    add_code_examples_to_supabase,
    update_source_info,
    extract_source_summary,
    search_code_examples
)

# Global dictionary for HITL sessions
hitl_sessions = {}

# Load environment variables from the project root .env file
project_root = Path(__file__).resolve().parent.parent
dotenv_path = project_root / '.env'

# Force override of existing environment variables
load_dotenv(dotenv_path, override=True)

# Create a dataclass for our application context
@dataclass
class Crawl4AIContext:
    """Context for the Crawl4AI MCP server."""
    crawler: AsyncWebCrawler
    supabase_client: Client
    reranking_model: Optional[CrossEncoder] = None

@asynccontextmanager
async def crawl4ai_lifespan(server: FastMCP) -> AsyncIterator[Crawl4AIContext]:
    """
    Manages the Crawl4AI client lifecycle.
    
    Args:
        server: The FastMCP server instance
        
    Yields:
        Crawl4AIContext: The context containing the Crawl4AI crawler and Supabase client
    """
    # Create browser configuration
    browser_config = BrowserConfig(
        headless=True, # Reverted to True
        verbose=False
    )
    
    # Initialize the crawler
    crawler = AsyncWebCrawler(config=browser_config)
    await crawler.__aenter__()
    
    # Initialize Supabase client
    supabase_client = get_supabase_client()
    
    # Initialize cross-encoder model for reranking if enabled
    reranking_model = None
    if os.getenv("USE_RERANKING", "false") == "true":
        try:
            reranking_model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        except Exception as e:
            print(f"Failed to load reranking model: {e}") # Original print
            reranking_model = None
    
    try:
        yield Crawl4AIContext(
            crawler=crawler,
            supabase_client=supabase_client,
            reranking_model=reranking_model
        )
    finally:
        # Clean up the crawler
        await crawler.__aexit__(None, None, None)

# Initialize FastMCP server
mcp = FastMCP(
    "mcp-crawl4ai-rag",
    description="MCP server for RAG and web crawling with Crawl4AI",
    lifespan=crawl4ai_lifespan,
    host=os.getenv("HOST", "0.0.0.0"),
    port=os.getenv("PORT", "8051")
)

def rerank_results(model: CrossEncoder, query: str, results: List[Dict[str, Any]], content_key: str = "content") -> List[Dict[str, Any]]:
    if not model or not results:
        return results
    try:
        texts = [result.get(content_key, "") for result in results]
        pairs = [[query, text] for text in texts]
        scores = model.predict(pairs)
        for i, result in enumerate(results):
            result["rerank_score"] = float(scores[i])
        reranked = sorted(results, key=lambda x: x.get("rerank_score", 0), reverse=True)
        return reranked
    except Exception as e:
        print(f"Error during reranking: {e}")
        return results

def is_sitemap(url: str) -> bool:
    return url.endswith('sitemap.xml') or 'sitemap' in urlparse(url).path

def is_txt(url: str) -> bool:
    return url.endswith('.txt')

def parse_sitemap(sitemap_url: str) -> List[str]:
    resp = requests.get(sitemap_url)
    urls = []
    if resp.status_code == 200:
        try:
            tree = ElementTree.fromstring(resp.content)
            urls = [loc.text for loc in tree.findall('.//{*}loc')]
        except Exception as e:
            print(f"Error parsing sitemap XML: {e}")
    return urls

def smart_chunk_markdown(text: str, chunk_size: int = 5000) -> List[str]:
    chunks = []
    start = 0
    text_length = len(text)
    while start < text_length:
        end = start + chunk_size
        if end >= text_length:
            chunks.append(text[start:].strip())
            break
        chunk = text[start:end]
        code_block = chunk.rfind('```')
        if code_block != -1 and code_block > chunk_size * 0.3:
            end = start + code_block
        elif '\n\n' in chunk:
            last_break = chunk.rfind('\n\n')
            if last_break > chunk_size * 0.3:
                end = start + last_break
        elif '. ' in chunk:
            last_period = chunk.rfind('. ')
            if last_period > chunk_size * 0.3:
                end = start + last_period + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end
    return chunks

def extract_section_info(chunk: str) -> Dict[str, Any]:
    headers = re.findall(r'^(#+)\s+(.+)$', chunk, re.MULTILINE)
    header_str = '; '.join([f'{h[0]} {h[1]}' for h in headers]) if headers else ''
    return {"headers": header_str, "char_count": len(chunk), "word_count": len(chunk.split())}

def process_code_example(args):
    code, context_before, context_after = args
    return generate_code_example_summary(code, context_before, context_after)

@mcp.tool()
async def crawl_single_page(ctx: Context, url: str, hitl_session_id: Optional[str] = None) -> str:
    using_hitl_session = False
    actual_session_id_for_cleanup = None
    supabase_client = ctx.request_context.lifespan_context.supabase_client
    final_crawler_to_use = None

    try:
        if hitl_session_id:
            if hitl_session_id in hitl_sessions:
                session_data = hitl_sessions[hitl_session_id]
                if isinstance(session_data, dict) and session_data.get('crawler'):
                    final_crawler_to_use = session_data['crawler']
                else:
                     return json.dumps({"success": False, "url": url, "error": "HITL session is invalid (no crawler)." })
                using_hitl_session = True
                actual_session_id_for_cleanup = hitl_session_id
                print(f"Using HITL session: {hitl_session_id} for URL: {url}")
            else:
                return json.dumps({"success": False, "url": url, "error": "Invalid or expired HITL session ID"})
        else:
            final_crawler_to_use = ctx.request_context.lifespan_context.crawler
            print(f"Using global crawler for URL: {url}")

        if not final_crawler_to_use: # Should not happen if logic above is correct
             return json.dumps({"success": False, "url": url, "error": "Crawler instance not available."})

        run_config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS, stream=False)
        result = await final_crawler_to_use.arun(url=url, config=run_config)
        
        if result.success and result.markdown:
            parsed_url = urlparse(url)
            source_id = parsed_url.netloc or parsed_url.path
            chunks = smart_chunk_markdown(result.markdown)
            urls_list = []
            chunk_numbers = []
            contents = []
            metadatas = []
            total_word_count = 0
            for i, chunk_content in enumerate(chunks): # Renamed chunk to chunk_content
                urls_list.append(url)
                chunk_numbers.append(i)
                contents.append(chunk_content)
                meta = extract_section_info(chunk_content)
                meta.update({"chunk_index": i, "url": url, "source": source_id,
                             "crawl_time": str(asyncio.current_task().get_coro().__name__)})
                metadatas.append(meta)
                total_word_count += meta.get("word_count", 0)
            
            url_to_full_document = {url: result.markdown}
            source_summary = extract_source_summary(source_id, result.markdown[:5000])
            update_source_info(supabase_client, source_id, source_summary, total_word_count)
            add_documents_to_supabase(supabase_client, urls_list, chunk_numbers, contents, metadatas, url_to_full_document)
            
            code_examples_list = []
            if os.getenv("USE_AGENTIC_RAG", "false") == "true":
                code_blocks = extract_code_blocks(result.markdown)
                if code_blocks:
                    code_urls_list, code_chunk_numbers_list, code_summaries_list, code_metadatas_list = [], [], [], []
                    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                        summary_args = [(block['code'], block['context_before'], block['context_after']) for block in code_blocks]
                        summaries = list(executor.map(process_code_example, summary_args))
                    for i, (block, summary) in enumerate(zip(code_blocks, summaries)):
                        code_urls_list.append(url)
                        code_chunk_numbers_list.append(i)
                        code_examples_list.append(block['code'])
                        code_summaries_list.append(summary)
                        code_meta = {"chunk_index": i, "url": url, "source": source_id,
                                     "char_count": len(block['code']), "word_count": len(block['code'].split())}
                        code_metadatas_list.append(code_meta)
                    if code_examples_list:
                        add_code_examples_to_supabase(
                            supabase_client, code_urls_list, code_chunk_numbers_list,
                            code_examples_list, code_summaries_list, code_metadatas_list
                        )
            
            return json.dumps({
                "success": True, "url": url, "chunks_stored": len(chunks),
                "code_examples_stored": len(code_examples_list),
                "content_length": len(result.markdown), "total_word_count": total_word_count,
                "source_id": source_id,
                "links_count": {"internal": len(result.links.get("internal", [])), "external": len(result.links.get("external", []))}
            }, indent=2)
        else:
            return json.dumps({"success": False, "url": url,
                               "error": result.error_message if result else "Crawler did not run or failed."}, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "url": url, "error": str(e)}, indent=2)
    finally:
        if using_hitl_session and actual_session_id_for_cleanup and actual_session_id_for_cleanup in hitl_sessions:
            session_to_cleanup = hitl_sessions.pop(actual_session_id_for_cleanup, None)
            if session_to_cleanup:
                crawler_instance_to_exit = session_to_cleanup.get('crawler')
                display_instance_to_stop = session_to_cleanup.get('display')
                fluxbox_process_to_terminate = session_to_cleanup.get('fluxbox_process')

                try:
                    if crawler_instance_to_exit:
                        await crawler_instance_to_exit.__aexit__(None, None, None)

                    if fluxbox_process_to_terminate and fluxbox_process_to_terminate.poll() is None:
                        fluxbox_process_to_terminate.terminate()
                        try:
                            fluxbox_process_to_terminate.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            fluxbox_process_to_terminate.kill()
                            print(f"HITL session {actual_session_id_for_cleanup}: fluxbox process killed after timeout.")
                        print(f"HITL session {actual_session_id_for_cleanup}: fluxbox process terminated.")

                    if display_instance_to_stop and hasattr(display_instance_to_stop, 'stop') and display_instance_to_stop.is_alive():
                        display_instance_to_stop.stop()

                    print(f"HITL session {actual_session_id_for_cleanup} for {url} closed and cleaned up.")
                except Exception as e_cleanup:
                    print(f"Error cleaning up HITL session {actual_session_id_for_cleanup} for {url}: {str(e_cleanup)}")

@mcp.tool()
async def smart_crawl_url(ctx: Context, url: str, max_depth: int = 3, max_concurrent: int = 10, chunk_size: int = 5000, hitl_session_id: Optional[str] = None) -> str:
    using_hitl_session = False
    actual_session_id_for_cleanup = None
    supabase_client = ctx.request_context.lifespan_context.supabase_client
    final_crawler_to_use = None

    try:
        if hitl_session_id:
            if hitl_session_id in hitl_sessions:
                session_data = hitl_sessions[hitl_session_id]
                if isinstance(session_data, dict) and session_data.get('crawler'):
                    final_crawler_to_use = session_data['crawler']
                else:
                    return json.dumps({"success": False, "url": url, "error": "HITL session is invalid (no crawler)." })
                using_hitl_session = True
                actual_session_id_for_cleanup = hitl_session_id
                print(f"Using HITL session: {hitl_session_id} for smart_crawl_url: {url}")
            else:
                return json.dumps({"success": False, "url": url, "error": "Invalid or expired HITL session ID"})
        else:
            final_crawler_to_use = ctx.request_context.lifespan_context.crawler
            print(f"Using global crawler for smart_crawl_url: {url}")
        
        if not final_crawler_to_use:
             return json.dumps({"success": False, "url": url, "error": "Crawler instance not available."})

        crawl_results = []
        crawl_type = None
        
        if is_txt(url):
            crawl_results = await crawl_markdown_file(final_crawler_to_use, url)
            crawl_type = "text_file"
        elif is_sitemap(url):
            sitemap_urls = parse_sitemap(url)
            if not sitemap_urls:
                return json.dumps({"success": False, "url": url, "error": "No URLs found in sitemap"}, indent=2)
            crawl_results = await crawl_batch(final_crawler_to_use, sitemap_urls, max_concurrent=max_concurrent)
            crawl_type = "sitemap"
        else:
            crawl_results = await crawl_recursive_internal_links(final_crawler_to_use, [url], max_depth=max_depth, max_concurrent=max_concurrent)
            crawl_type = "webpage"
        
        if not crawl_results:
            return json.dumps({"success": False, "url": url, "error": "No content found"}, indent=2)
        
        urls_list, chunk_numbers, contents, metadatas = [], [], [], []
        chunk_count = 0
        source_content_map, source_word_counts = {}, {}
        
        for doc in crawl_results:
            source_url_loop = doc['url'] # Renamed to avoid conflict
            md = doc['markdown']
            chunks = smart_chunk_markdown(md, chunk_size=chunk_size)
            parsed_url_loop = urlparse(source_url_loop) # Renamed
            source_id_loop = parsed_url_loop.netloc or parsed_url_loop.path # Renamed
            if source_id_loop not in source_content_map:
                source_content_map[source_id_loop] = md[:5000]
                source_word_counts[source_id_loop] = 0
            for i, chunk_content in enumerate(chunks): # Renamed
                urls_list.append(source_url_loop)
                chunk_numbers.append(i)
                contents.append(chunk_content)
                meta = extract_section_info(chunk_content)
                meta.update({"chunk_index": i, "url": source_url_loop, "source": source_id_loop, "crawl_type": crawl_type,
                             "crawl_time": str(asyncio.current_task().get_coro().__name__)})
                metadatas.append(meta)
                source_word_counts[source_id_loop] += meta.get("word_count", 0)
                chunk_count += 1
        
        url_to_full_document = {doc['url']: doc['markdown'] for doc in crawl_results}
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            source_summary_args = [(sid, content) for sid, content in source_content_map.items()]
            source_summaries = list(executor.map(lambda args_lambda: extract_source_summary(args_lambda[0], args_lambda[1]), source_summary_args))
        
        for (source_id_loop, _), summary in zip(source_summary_args, source_summaries): # Renamed
            update_source_info(supabase_client, source_id_loop, summary, source_word_counts.get(source_id_loop, 0))
        
        add_documents_to_supabase(supabase_client, urls_list, chunk_numbers, contents, metadatas, url_to_full_document, batch_size=20)
        
        code_examples_list_outer = []
        if os.getenv("USE_AGENTIC_RAG", "false") == "true":
            code_urls_list_outer, code_chunk_numbers_outer, code_summaries_outer, code_metadatas_list_outer = [], [], [], []
            for doc in crawl_results:
                code_blocks = extract_code_blocks(doc['markdown'])
                if code_blocks:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                        summary_args = [(block['code'], block['context_before'], block['context_after']) for block in code_blocks]
                        summaries = list(executor.map(process_code_example, summary_args))
                    parsed_url_loop = urlparse(doc['url']) # Renamed
                    source_id_loop = parsed_url_loop.netloc or parsed_url_loop.path # Renamed
                    for i, (block, summary) in enumerate(zip(code_blocks, summaries)):
                        code_urls_list_outer.append(doc['url'])
                        code_chunk_numbers_outer.append(len(code_examples_list_outer))
                        code_examples_list_outer.append(block['code'])
                        code_summaries_outer.append(summary)
                        code_meta = {"chunk_index": len(code_examples_list_outer) - 1, "url": doc['url'], "source": source_id_loop,
                                     "char_count": len(block['code']), "word_count": len(block['code'].split())}
                        code_metadatas_list_outer.append(code_meta)
            if code_examples_list_outer:
                add_code_examples_to_supabase(
                    supabase_client, code_urls_list_outer, code_chunk_numbers_outer,
                    code_examples_list_outer, code_summaries_outer, code_metadatas_list_outer, batch_size=20
                )
        
        return json.dumps({
            "success": True, "url": url, "crawl_type": crawl_type, "pages_crawled": len(crawl_results),
            "chunks_stored": chunk_count, "code_examples_stored": len(code_examples_list_outer),
            "sources_updated": len(source_content_map),
            "urls_crawled": [doc['url'] for doc in crawl_results][:5] + (["..."] if len(crawl_results) > 5 else [])
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "url": url, "error": str(e)}, indent=2)
    finally:
        if using_hitl_session and actual_session_id_for_cleanup and actual_session_id_for_cleanup in hitl_sessions:
            session_to_cleanup = hitl_sessions.pop(actual_session_id_for_cleanup, None)
            if session_to_cleanup:
                crawler_instance_to_exit = session_to_cleanup.get('crawler')
                display_instance_to_stop = session_to_cleanup.get('display')
                fluxbox_process_to_terminate = session_to_cleanup.get('fluxbox_process')
                # x_app_process_to_terminate = session_to_cleanup.get('x_app_process') # Removed

                try:
                    if crawler_instance_to_exit:
                        await crawler_instance_to_exit.__aexit__(None, None, None)

                    # Removed x_app_process termination

                    if fluxbox_process_to_terminate and fluxbox_process_to_terminate.poll() is None:
                        fluxbox_process_to_terminate.terminate()
                        try:
                            fluxbox_process_to_terminate.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            fluxbox_process_to_terminate.kill()
                            print(f"HITL session {actual_session_id_for_cleanup}: fluxbox process killed after timeout for smart_crawl_url.")
                        print(f"HITL session {actual_session_id_for_cleanup}: fluxbox process terminated for smart_crawl_url.")

                    if display_instance_to_stop and hasattr(display_instance_to_stop, 'stop') and display_instance_to_stop.is_alive():
                        display_instance_to_stop.stop()
                    print(f"HITL session {actual_session_id_for_cleanup} for smart_crawl_url {url} closed and cleaned up.")
                except Exception as e_cleanup:
                    print(f"Error cleaning up HITL session {actual_session_id_for_cleanup} for smart_crawl_url {url}: {str(e_cleanup)}")

@mcp.tool()
async def get_available_sources(ctx: Context) -> str:
    """
    Get all available sources from the sources table.
    
    This tool returns a list of all unique sources (domains) that have been crawled and stored
    in the database, along with their summaries and statistics. This is useful for discovering 
    what content is available for querying.

    Always use this tool before calling the RAG query or code example query tool
    with a specific source filter!
    
    Args:
        ctx: The MCP server provided context
    
    Returns:
        JSON string with the list of available sources and their details
    """
    try:
        # Get the Supabase client from the context
        supabase_client = ctx.request_context.lifespan_context.supabase_client
        
        # Query the sources table directly
        result = supabase_client.from_('sources')\
            .select('*')\
            .order('source_id')\
            .execute()
        
        # Format the sources with their details
        sources = []
        if result.data:
            for source in result.data:
                sources.append({
                    "source_id": source.get("source_id"),
                    "summary": source.get("summary"),
                    "total_words": source.get("total_words"),
                    "created_at": source.get("created_at"),
                    "updated_at": source.get("updated_at")
                })
        
        return json.dumps({
            "success": True,
            "sources": sources,
            "count": len(sources)
        }, indent=2)
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, indent=2)

@mcp.tool()
async def perform_rag_query(ctx: Context, query: str, source: str = None, match_count: int = 5) -> str:
    # ... (content of perform_rag_query - assumed unchanged)
    try:
        # Get the Supabase client from the context
        supabase_client = ctx.request_context.lifespan_context.supabase_client
        
        # Check if hybrid search is enabled
        use_hybrid_search = os.getenv("USE_HYBRID_SEARCH", "false") == "true"
        
        # Prepare filter if source is provided and not empty
        filter_metadata = None
        if source and source.strip():
            filter_metadata = {"source": source}
        
        if use_hybrid_search:
            # Hybrid search: combine vector and keyword search
            
            # 1. Get vector search results (get more to account for filtering)
            vector_results = search_documents(
                client=supabase_client,
                query=query,
                match_count=match_count * 2,  # Get double to have room for filtering
                filter_metadata=filter_metadata
            )
            
            # 2. Get keyword search results using ILIKE
            keyword_query = supabase_client.from_('crawled_pages')\
                .select('id, url, chunk_number, content, metadata, source_id')\
                .ilike('content', f'%{query}%')
            
            # Apply source filter if provided
            if source and source.strip():
                keyword_query = keyword_query.eq('source_id', source)
            
            # Execute keyword search
            keyword_response = keyword_query.limit(match_count * 2).execute()
            keyword_results = keyword_response.data if keyword_response.data else []
            
            # 3. Combine results with preference for items appearing in both
            seen_ids = set()
            combined_results = []
            
            # First, add items that appear in both searches (these are the best matches)
            vector_ids = {r.get('id') for r in vector_results if r.get('id')}
            for kr in keyword_results:
                if kr['id'] in vector_ids and kr['id'] not in seen_ids:
                    # Find the vector result to get similarity score
                    for vr in vector_results:
                        if vr.get('id') == kr['id']:
                            # Boost similarity score for items in both results
                            vr['similarity'] = min(1.0, vr.get('similarity', 0) * 1.2)
                            combined_results.append(vr)
                            seen_ids.add(kr['id'])
                            break
            
            # Then add remaining vector results (semantic matches without exact keyword)
            for vr in vector_results:
                if vr.get('id') and vr['id'] not in seen_ids and len(combined_results) < match_count:
                    combined_results.append(vr)
                    seen_ids.add(vr['id'])
            
            # Finally, add pure keyword matches if we still need more results
            for kr in keyword_results:
                if kr['id'] not in seen_ids and len(combined_results) < match_count:
                    # Convert keyword result to match vector result format
                    combined_results.append({
                        'id': kr['id'],
                        'url': kr['url'],
                        'chunk_number': kr['chunk_number'],
                        'content': kr['content'],
                        'metadata': kr['metadata'],
                        'source_id': kr['source_id'],
                        'similarity': 0.5  # Default similarity for keyword-only matches
                    })
                    seen_ids.add(kr['id'])
            
            # Use combined results
            results = combined_results[:match_count]
            
        else:
            # Standard vector search only
            results = search_documents(
                client=supabase_client,
                query=query,
                match_count=match_count,
                filter_metadata=filter_metadata
            )
        
        # Apply reranking if enabled
        use_reranking = os.getenv("USE_RERANKING", "false") == "true"
        if use_reranking and ctx.request_context.lifespan_context.reranking_model:
            results = rerank_results(ctx.request_context.lifespan_context.reranking_model, query, results, content_key="content")
        
        # Format the results
        formatted_results = []
        for result in results:
            formatted_result = {
                "url": result.get("url"),
                "content": result.get("content"),
                "metadata": result.get("metadata"),
                "similarity": result.get("similarity")
            }
            # Include rerank score if available
            if "rerank_score" in result:
                formatted_result["rerank_score"] = result["rerank_score"]
            formatted_results.append(formatted_result)
        
        return json.dumps({
            "success": True,
            "query": query,
            "source_filter": source,
            "search_mode": "hybrid" if use_hybrid_search else "vector",
            "reranking_applied": use_reranking and ctx.request_context.lifespan_context.reranking_model is not None,
            "results": formatted_results,
            "count": len(formatted_results)
        }, indent=2)
    except Exception as e:
        return json.dumps({
            "success": False,
            "query": query,
            "error": str(e)
        }, indent=2)

@mcp.tool()
async def search_code_examples(ctx: Context, query: str, source_id: str = None, match_count: int = 5) -> str:
    # ... (content of search_code_examples - assumed unchanged)
    # Check if code example extraction is enabled
    extract_code_examples_enabled = os.getenv("USE_AGENTIC_RAG", "false") == "true"
    if not extract_code_examples_enabled:
        return json.dumps({
            "success": False,
            "error": "Code example extraction is disabled. Perform a normal RAG search."
        }, indent=2)
    
    try:
        # Get the Supabase client from the context
        supabase_client = ctx.request_context.lifespan_context.supabase_client
        
        # Check if hybrid search is enabled
        use_hybrid_search = os.getenv("USE_HYBRID_SEARCH", "false") == "true"
        
        # Prepare filter if source is provided and not empty
        filter_metadata = None
        if source_id and source_id.strip():
            filter_metadata = {"source": source_id}
        
        if use_hybrid_search:
            # Hybrid search: combine vector and keyword search
            
            # Import the search function from utils
            from utils import search_code_examples as search_code_examples_impl
            
            # 1. Get vector search results (get more to account for filtering)
            vector_results = search_code_examples_impl(
                client=supabase_client,
                query=query,
                match_count=match_count * 2,  # Get double to have room for filtering
                filter_metadata=filter_metadata
            )
            
            # 2. Get keyword search results using ILIKE on both content and summary
            keyword_query = supabase_client.from_('code_examples')\
                .select('id, url, chunk_number, content, summary, metadata, source_id')\
                .or_(f'content.ilike.%{query}%,summary.ilike.%{query}%')
            
            # Apply source filter if provided
            if source_id and source_id.strip():
                keyword_query = keyword_query.eq('source_id', source_id)
            
            # Execute keyword search
            keyword_response = keyword_query.limit(match_count * 2).execute()
            keyword_results = keyword_response.data if keyword_response.data else []
            
            # 3. Combine results with preference for items appearing in both
            seen_ids = set()
            combined_results = []
            
            # First, add items that appear in both searches (these are the best matches)
            vector_ids = {r.get('id') for r in vector_results if r.get('id')}
            for kr in keyword_results:
                if kr['id'] in vector_ids and kr['id'] not in seen_ids:
                    # Find the vector result to get similarity score
                    for vr in vector_results:
                        if vr.get('id') == kr['id']:
                            # Boost similarity score for items in both results
                            vr['similarity'] = min(1.0, vr.get('similarity', 0) * 1.2)
                            combined_results.append(vr)
                            seen_ids.add(kr['id'])
                            break
            
            # Then add remaining vector results (semantic matches without exact keyword)
            for vr in vector_results:
                if vr.get('id') and vr['id'] not in seen_ids and len(combined_results) < match_count:
                    combined_results.append(vr)
                    seen_ids.add(vr['id'])
            
            # Finally, add pure keyword matches if we still need more results
            for kr in keyword_results:
                if kr['id'] not in seen_ids and len(combined_results) < match_count:
                    # Convert keyword result to match vector result format
                    combined_results.append({
                        'id': kr['id'],
                        'url': kr['url'],
                        'chunk_number': kr['chunk_number'],
                        'content': kr['content'],
                        'summary': kr['summary'],
                        'metadata': kr['metadata'],
                        'source_id': kr['source_id'],
                        'similarity': 0.5  # Default similarity for keyword-only matches
                    })
                    seen_ids.add(kr['id'])
            
            # Use combined results
            results = combined_results[:match_count]
            
        else:
            # Standard vector search only
            from utils import search_code_examples as search_code_examples_impl
            
            results = search_code_examples_impl(
                client=supabase_client,
                query=query,
                match_count=match_count,
                filter_metadata=filter_metadata
            )
        
        # Apply reranking if enabled
        use_reranking = os.getenv("USE_RERANKING", "false") == "true"
        if use_reranking and ctx.request_context.lifespan_context.reranking_model:
            results = rerank_results(ctx.request_context.lifespan_context.reranking_model, query, results, content_key="content")
        
        # Format the results
        formatted_results = []
        for result in results:
            formatted_result = {
                "url": result.get("url"),
                "code": result.get("content"),
                "summary": result.get("summary"),
                "metadata": result.get("metadata"),
                "source_id": result.get("source_id"),
                "similarity": result.get("similarity")
            }
            # Include rerank score if available
            if "rerank_score" in result:
                formatted_result["rerank_score"] = result["rerank_score"]
            formatted_results.append(formatted_result)
        
        return json.dumps({
            "success": True,
            "query": query,
            "source_filter": source_id,
            "search_mode": "hybrid" if use_hybrid_search else "vector",
            "reranking_applied": use_reranking and ctx.request_context.lifespan_context.reranking_model is not None,
            "results": formatted_results,
            "count": len(formatted_results)
        }, indent=2)
    except Exception as e:
        return json.dumps({
            "success": False,
            "query": query,
            "error": str(e)
        }, indent=2)

@mcp.tool()
async def initiate_human_in_the_loop(ctx: Context, url: str) -> str:
    session_id = str(uuid.uuid4())
    disp = None
    hitl_crawler = None # Initialize hitl_crawler
    fluxbox_process = None
    # x_app_process = None # Removed for xeyes revert

    vnc_port_str = os.getenv("VNC_PORT", "5901")
    novnc_port_str = os.getenv("NOVNC_PORT", "6080")
    app_external_hostname = os.getenv("APP_EXTERNAL_HOSTNAME", "localhost")

    try:
        vnc_port = int(vnc_port_str)
        novnc_port = int(novnc_port_str)

        print(f"Attempting to start PyVirtualDisplay Xvnc on VNC port {vnc_port}")
        disp = Display(
            backend="xvnc",
            rfbport=vnc_port,
            size=(1280, 1024),
            color_depth=24,
        )
        disp.start()
        print(f"PyVirtualDisplay Xvnc started on DISPLAY {disp.display}, using configured rfbport {vnc_port}.")

        try:
            fluxbox_env = disp.env()
            print(f"Attempting to start fluxbox on display {disp.display}...")
            fluxbox_process = subprocess.Popen(
                ["fluxbox"],
                env=fluxbox_env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            await asyncio.sleep(0.5)

            if fluxbox_process.poll() is not None:
                print(f"WARNING: fluxbox may have failed to start. Exit code: {fluxbox_process.returncode}. The VNC session might be a black screen or unusable.")
            else:
                print("Fluxbox process started (or starting) in the background.")
        except Exception as fb_exc:
            print(f"WARNING: Failed to start fluxbox: {fb_exc}. Proceeding without window manager. VNC session might be black or unusable.")
            fluxbox_process = None

        # Restore browser launch logic
        browser_config = BrowserConfig(
            browser_type="firefox",
            headless=False,
            extra_args=[], # Explicitly empty for Firefox
            verbose=True
            # Optional: add/ensure viewport_width=1280, viewport_height=1024 if needed
        )

        hitl_crawler = AsyncWebCrawler(config=browser_config)
        await hitl_crawler.__aenter__()
        print(f"AsyncWebCrawler started within virtual display {disp.display}.")

        # Navigate to the initial URL using the crawler's underlying page object if possible.
        try:
            if hasattr(hitl_crawler, 'page') and hitl_crawler.page:
                 await hitl_crawler.page.goto(url, timeout=60000)
            elif hasattr(hitl_crawler, '_get_playwright_page'):
                page = await hitl_crawler._get_playwright_page(new_page=True)
                await page.goto(url, timeout=60000)
            print(f"Browser navigated to {url} in Xvnc display {disp.display}.")
        except Exception as nav_exc:
            print(f"Note: HITL browser initiated, but failed to automatically navigate to {url} in Xvnc: {nav_exc}")

        hitl_sessions[session_id] = {
            'crawler': hitl_crawler,
            'display': disp,
            'vnc_port': vnc_port,
            'fluxbox_process': fluxbox_process
            # 'x_app_process' key removed
        }

        novnc_url = f"http://{app_external_hostname}:{novnc_port}/vnc.html"

        return json.dumps({
            "success": True,
            "session_id": session_id,
            "novnc_url": novnc_url,
            "message": (
                f"HITL session initiated with Xvnc on display {disp.display} (VNC port {vnc_port}). "
                f"Connect via noVNC URL: {novnc_url}. Browser is Firefox. " # Restored message
                "Call resume_from_human_in_the_loop with session_id when done."
            )
        })

    except Exception as e:
        print(f"Error in initiate_human_in_the_loop: {str(e)}")
        if hitl_crawler and hasattr(hitl_crawler, '_browser_context') and hitl_crawler._browser_context:
            try:
                await hitl_crawler.__aexit__(None, None, None)
                print("HITL crawler exited during initiation failure cleanup.")
            except Exception as crawler_cleanup_exc:
                print(f"Error cleaning up HITL crawler during initiation failure: {crawler_cleanup_exc}")

        # Removed x_app_process cleanup from here

        if fluxbox_process and fluxbox_process.poll() is None:
            try:
                fluxbox_process.terminate()
                fluxbox_process.wait(timeout=1)
                print("Fluxbox process terminated during initiation failure cleanup.")
            except subprocess.TimeoutExpired:
                fluxbox_process.kill()
                print("Fluxbox process killed during initiation failure cleanup.")
            except Exception as fb_cleanup_exc:
                 print(f"Error cleaning up fluxbox process during initiation failure: {fb_cleanup_exc}")

        if disp and disp.is_alive():
            try:
                disp.stop()
                print("PyVirtualDisplay stopped during initiation failure cleanup.")
            except Exception as disp_cleanup_exc:
                print(f"Error cleaning up PyVirtualDisplay during initiation failure: {disp_cleanup_exc}")
        return json.dumps({"success": False, "error": f"Failed to initiate HITL VNC session: {str(e)}"})

@mcp.tool()
async def resume_from_human_in_the_loop(ctx: Context, session_id: str) -> str:
    # ... (resume_from_human_in_the_loop - assumed unchanged from previous correct state)
    try:
        if session_id not in hitl_sessions:
            return json.dumps({
                "success": False,
                "session_id": session_id,
                "error": "Invalid or expired session_id. Please initiate a new HITL session."
            })
        return json.dumps({
            "success": True,
            "session_id": session_id,
            "message": "Human interaction phase complete. The browser session (if still active) can now be used by other tools that support HITL sessions."
        })
    except Exception as e:
        return json.dumps({
            "success": False,
            "session_id": session_id,
            "error": f"Error in resume_from_human_in_the_loop: {str(e)}"
        })

async def crawl_markdown_file(crawler: AsyncWebCrawler, url: str) -> List[Dict[str, Any]]:
    # ... (crawl_markdown_file - assumed unchanged)
    crawl_config = CrawlerRunConfig()
    result = await crawler.arun(url=url, config=crawl_config)
    if result.success and result.markdown:
        return [{'url': url, 'markdown': result.markdown}]
    else:
        print(f"Failed to crawl {url}: {result.error_message}")
        return []

async def crawl_batch(crawler: AsyncWebCrawler, urls: List[str], max_concurrent: int = 10) -> List[Dict[str, Any]]:
    # ... (crawl_batch - assumed unchanged)
    crawl_config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS, stream=False)
    dispatcher = MemoryAdaptiveDispatcher(
        memory_threshold_percent=70.0,
        check_interval=1.0,
        max_session_permit=max_concurrent
    )
    results = await crawler.arun_many(urls=urls, config=crawl_config, dispatcher=dispatcher)
    return [{'url': r.url, 'markdown': r.markdown} for r in results if r.success and r.markdown]

async def crawl_recursive_internal_links(crawler: AsyncWebCrawler, start_urls: List[str], max_depth: int = 3, max_concurrent: int = 10) -> List[Dict[str, Any]]:
    # ... (crawl_recursive_internal_links - assumed unchanged)
    run_config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS, stream=False)
    dispatcher = MemoryAdaptiveDispatcher(
        memory_threshold_percent=70.0,
        check_interval=1.0,
        max_session_permit=max_concurrent
    )
    visited = set()
    def normalize_url(u): # Renamed url to u to avoid conflict
        return urldefrag(u)[0]
    current_urls = set([normalize_url(u) for u in start_urls])
    results_all = []
    for depth in range(max_depth):
        urls_to_crawl = [u_norm for u_norm in current_urls if u_norm not in visited] # Renamed url to u_norm
        if not urls_to_crawl:
            break
        results = await crawler.arun_many(urls=urls_to_crawl, config=run_config, dispatcher=dispatcher)
        next_level_urls = set()
        for result in results:
            norm_url = normalize_url(result.url)
            visited.add(norm_url)
            if result.success and result.markdown:
                results_all.append({'url': result.url, 'markdown': result.markdown})
                for link in result.links.get("internal", []):
                    next_url = normalize_url(link["href"])
                    if next_url not in visited:
                        next_level_urls.add(next_url)
        current_urls = next_level_urls
    return results_all

async def main():
    transport = os.getenv("TRANSPORT", "sse")
    if transport == 'sse':
        await mcp.run_sse_async()
    else:
        await mcp.run_stdio_async()

if __name__ == "__main__":
    asyncio.run(main())