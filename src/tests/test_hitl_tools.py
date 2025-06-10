import unittest
from unittest.mock import patch, AsyncMock, MagicMock, PropertyMock
import json
import uuid
import re # Ensure re is imported for patching if initiate_human_in_the_loop uses it directly

# Adjust the path if necessary for your test execution environment
# This assumes that 'src' is in PYTHONPATH or the tests are run from the project root.
from src.crawl4ai_mcp import (
    initiate_human_in_the_loop,
    resume_from_human_in_the_loop,
    hitl_sessions,
    Context,
    crawl_single_page,
    smart_crawl_url,
    # Crawl4AIContext,
    # CrawlerRunConfig, # Imported in crawl4ai_mcp, usually no need to mock its instantiation directly
)
from crawl4ai import CrawlerRunConfig # For type hinting and potentially for spec if needed

# AsyncWebCrawler and BrowserConfig are imported in crawl4ai_mcp, so we patch them there.

# A helper function to create a mock crawl result
def create_mock_crawl_result(success=True, markdown="Some markdown", links=None, error_message=None):
    mock_result = MagicMock()
    mock_result.success = success
    mock_result.markdown = markdown
    mock_result.links = links if links is not None else {"internal": [], "external": []}
    mock_result.error_message = error_message
    return mock_result

class TestHITLTools(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        """Clear HITL sessions before each test and prepare a mock context."""
        hitl_sessions.clear()
        self.mock_ctx = MagicMock(spec=Context)
        # Mock the context structure needed by the tools
        self.mock_ctx.request_context = MagicMock()
        self.mock_ctx.request_context.lifespan_context = MagicMock()
        # Provide a mock Supabase client as it's used for storing data
        self.mock_ctx.request_context.lifespan_context.supabase_client = MagicMock()
        # Provide a mock global crawler for tests not using HITL
        self.mock_global_crawler = AsyncMock(spec_set=True) # Use spec_set for stricter mocking if methods are known
        self.mock_ctx.request_context.lifespan_context.crawler = self.mock_global_crawler


    def tearDown(self):
        """Clear HITL sessions after each test to prevent state leakage."""
        hitl_sessions.clear()

    @patch('src.crawl4ai_mcp.BrowserConfig')
    @patch('src.crawl4ai_mcp.AsyncWebCrawler')
    async def test_initiate_success(self, MockAsyncWebCrawler, MockBrowserConfig):
        """Test successful initiation of a HITL session."""
        mock_crawler_instance = AsyncMock()

        # Mocking the ws_endpoint retrieval for debugging port
        # Path 1: hitl_crawler._browser_context._browser.ws_endpoint
        mock_crawler_instance._browser_context = MagicMock()
        mock_crawler_instance._browser_context._browser = MagicMock()
        mock_crawler_instance._browser_context._browser.ws_endpoint = "ws://127.0.0.1:12345/devtools/browser/someid"

        # Path 2: hitl_crawler.browser.ws_endpoint (fallback or alternative)
        # To ensure the first path is taken, we can make this one less attractive or not set.
        # Or, ensure the primary mock path is sufficient.

        MockAsyncWebCrawler.return_value = mock_crawler_instance

        mock_browser_config_instance = MagicMock()
        MockBrowserConfig.return_value = mock_browser_config_instance

        target_url = "http://example.com"
        response_str = await initiate_human_in_the_loop(self.mock_ctx, target_url)
        response = json.loads(response_str)

        self.assertTrue(response["success"], f"Response was not successful: {response.get('error')}")
        self.assertIn("session_id", response)
        self.assertIn("debugging_url", response)
        self.assertEqual(response["debugging_url"], "http://127.0.0.1:12345")

        session_id = response["session_id"]
        self.assertIn(session_id, hitl_sessions)
        self.assertEqual(hitl_sessions[session_id], mock_crawler_instance)

        mock_crawler_instance.__aenter__.assert_called_once()
        MockBrowserConfig.assert_called_once_with(
            headless=False,
            browser_args=["--remote-debugging-port=0", "--disable-gpu", "--no-sandbox"],
            verbose=True
        )
        MockAsyncWebCrawler.assert_called_once_with(config=mock_browser_config_instance)

        # Clean up the session that was added by the tool to allow __aexit__ to be called
        if session_id in hitl_sessions:
            # Ensure __aexit__ is awaitable if it's an AsyncMock
            if hasattr(hitl_sessions[session_id], '__aexit__') and asyncio.iscoroutinefunction(hitl_sessions[session_id].__aexit__):
                await hitl_sessions[session_id].__aexit__(None, None, None)
            elif hasattr(hitl_sessions[session_id], '__aexit__'): # If it's a MagicMock not AsyncMock
                 hitl_sessions[session_id].__aexit__(None,None,None)
            del hitl_sessions[session_id]


    @patch('src.crawl4ai_mcp.BrowserConfig')
    @patch('src.crawl4ai_mcp.AsyncWebCrawler')
    async def test_initiate_port_retrieval_failure_no_ws_endpoint(self, MockAsyncWebCrawler, MockBrowserConfig):
        """Test HITL initiation when ws_endpoint is not available."""
        mock_crawler_instance = AsyncMock()

        # Simulate failure to get ws_endpoint by having the attributes missing or returning None
        # Path 1: _browser_context pathway
        mock_crawler_instance._browser_context = MagicMock()
        mock_crawler_instance._browser_context._browser = MagicMock()
        mock_crawler_instance._browser_context._browser.ws_endpoint = None # Explicitly None

        # Path 2: .browser pathway (ensure this also fails)
        # We can use PropertyMock for attributes if they are properties
        type(mock_crawler_instance).browser = PropertyMock(return_value=MagicMock(ws_endpoint=None))


        MockAsyncWebCrawler.return_value = mock_crawler_instance
        MockBrowserConfig.return_value = MagicMock()

        response_str = await initiate_human_in_the_loop(self.mock_ctx, "http://example.com")
        response = json.loads(response_str)

        self.assertFalse(response["success"])
        self.assertIn("error", response)
        self.assertIn("Could not determine browser debugging port", response["error"])
        self.assertEqual(len(hitl_sessions), 0)

        mock_crawler_instance.__aenter__.assert_called_once()
        mock_crawler_instance.__aexit__.assert_called_once() # Should be called on failure after __aenter__

    @patch('src.crawl4ai_mcp.BrowserConfig')
    @patch('src.crawl4ai_mcp.AsyncWebCrawler')
    async def test_initiate_port_retrieval_failure_regex_miss(self, MockAsyncWebCrawler, MockBrowserConfig):
        """Test HITL initiation when ws_endpoint is malformed."""
        mock_crawler_instance = AsyncMock()

        mock_crawler_instance._browser_context = MagicMock()
        mock_crawler_instance._browser_context._browser = MagicMock()
        mock_crawler_instance._browser_context._browser.ws_endpoint = "ws://invalid_url_no_port" # Malformed

        type(mock_crawler_instance).browser = PropertyMock(return_value=MagicMock(ws_endpoint="ws://invalid_url_no_port"))

        MockAsyncWebCrawler.return_value = mock_crawler_instance
        MockBrowserConfig.return_value = MagicMock()

        response_str = await initiate_human_in_the_loop(self.mock_ctx, "http://example.com")
        response = json.loads(response_str)

        self.assertFalse(response["success"])
        self.assertIn("error", response)
        self.assertIn("Could not determine browser debugging port", response["error"])
        self.assertEqual(len(hitl_sessions), 0)
        mock_crawler_instance.__aenter__.assert_called_once()
        mock_crawler_instance.__aexit__.assert_called_once()


    @patch('src.crawl4ai_mcp.BrowserConfig')
    @patch('src.crawl4ai_mcp.AsyncWebCrawler')
    async def test_initiate_browser_launch_exception(self, MockAsyncWebCrawler, MockBrowserConfig):
        """Test HITL initiation when browser launch (__aenter__) fails."""
        mock_crawler_instance = AsyncMock()
        mock_crawler_instance.__aenter__.side_effect = Exception("Browser launch failed")

        MockAsyncWebCrawler.return_value = mock_crawler_instance
        MockBrowserConfig.return_value = MagicMock()

        response_str = await initiate_human_in_the_loop(self.mock_ctx, "http://example.com")
        response = json.loads(response_str)

        self.assertFalse(response["success"])
        self.assertIn("error", response)
        self.assertIn("Failed to initiate HITL session: Browser launch failed", response["error"])
        self.assertEqual(len(hitl_sessions), 0)

        mock_crawler_instance.__aenter__.assert_called_once()
        mock_crawler_instance.__aexit__.assert_not_called() # __aexit__ shouldn't be called if __aenter__ fails

    async def test_resume_success(self):
        """Test successful resumption of a valid HITL session."""
        session_id = str(uuid.uuid4())
        # The value in hitl_sessions is the crawler instance. For this test, it can be a simple mock.
        hitl_sessions[session_id] = MagicMock(spec_set=['__aenter__', '__aexit__']) # spec_set for strict mocking

        response_str = await resume_from_human_in_the_loop(self.mock_ctx, session_id)
        response = json.loads(response_str)

        self.assertTrue(response["success"])
        self.assertEqual(response["session_id"], session_id)
        self.assertIn("Human interaction phase complete", response["message"])
        self.assertIn(session_id, hitl_sessions) # Session should still be there

    async def test_resume_invalid_session(self):
        """Test resumption with an invalid or expired session ID."""
        non_existent_session_id = str(uuid.uuid4())
        response_str = await resume_from_human_in_the_loop(self.mock_ctx, non_existent_session_id)
        response = json.loads(response_str)

        self.assertFalse(response["success"])
        self.assertEqual(response["session_id"], non_existent_session_id)
        self.assertIn("error", response)
        self.assertIn("Invalid or expired session_id", response["error"])

    @patch('src.crawl4ai_mcp.BrowserConfig')
    @patch('src.crawl4ai_mcp.AsyncWebCrawler')
    async def test_initiate_navigation_attempt(self, MockAsyncWebCrawler, MockBrowserConfig):
        """Test that navigation is attempted during successful initiation."""
        mock_crawler_instance = AsyncMock()
        mock_crawler_instance._browser_context = MagicMock()
        mock_crawler_instance._browser_context._browser = MagicMock()
        mock_crawler_instance._browser_context._browser.ws_endpoint = "ws://127.0.0.1:12345/devtools/browser/someid"

        # Mock the page and goto attributes/methods for navigation
        mock_page = AsyncMock()
        # Path 1: hitl_crawler.page.goto(url)
        mock_crawler_instance.page = mock_page
        # Path 2: hitl_crawler._get_playwright_page().goto(url)
        # mock_crawler_instance._get_playwright_page = AsyncMock(return_value=mock_page)


        MockAsyncWebCrawler.return_value = mock_crawler_instance
        MockBrowserConfig.return_value = MagicMock()

        target_url = "http://example.com/navigate"
        response_str = await initiate_human_in_the_loop(self.mock_ctx, target_url)
        response = json.loads(response_str)

        self.assertTrue(response["success"])
        session_id = response["session_id"]

        # Check if navigation was attempted
        # Based on current implementation: tries `hitl_crawler.page.goto` then `hitl_crawler._get_playwright_page`
        # If `hitl_crawler.page` exists:
        mock_crawler_instance.page.goto.assert_called_once_with(target_url, timeout=60000)
        # Or if `_get_playwright_page` was used (if .page was None or didn't exist):
        # mock_crawler_instance._get_playwright_page.assert_called_once_with(new_page=True)
        # mock_page.goto.assert_called_once_with(target_url, timeout=60000)

        # Clean up
        if session_id in hitl_sessions: # type: ignore
            crawler_to_clean = hitl_sessions.pop(session_id, None) # type: ignore
            if crawler_to_clean and hasattr(crawler_to_clean, '__aexit__'):
                 if asyncio.iscoroutinefunction(crawler_to_clean.__aexit__):
                    await crawler_to_clean.__aexit__(None, None, None)
                 else:
                    crawler_to_clean.__aexit__(None, None, None)


    # --- Tests for crawl_single_page with HITL ---

    @patch('src.crawl4ai_mcp.extract_code_blocks', return_value=[]) # Assume no code blocks for simplicity
    @patch('src.crawl4ai_mcp.update_source_info')
    @patch('src.crawl4ai_mcp.extract_source_summary')
    @patch('src.crawl4ai_mcp.add_documents_to_supabase')
    async def test_crawl_single_page_with_hitl_success(self, mock_add_docs, mock_extract_summary, mock_update_source, mock_extract_code):
        session_id = str(uuid.uuid4())
        mock_hitl_crawler = AsyncMock(spec=True) # Use spec for stricter attribute checking if AsyncWebCrawler is complex
        mock_hitl_crawler.arun.return_value = create_mock_crawl_result(markdown="HITL crawled content")
        # mock_hitl_crawler.__aexit__ = AsyncMock() # Not needed if using AsyncMock(spec=True) as __aexit__ is part of protocol

        hitl_sessions[session_id] = mock_hitl_crawler
        mock_extract_summary.return_value = "Summary"

        response_str = await crawl_single_page(self.mock_ctx, "http://example.com/hitl_page", hitl_session_id=session_id)
        response = json.loads(response_str)

        self.assertTrue(response["success"])
        self.assertEqual(response["content_length"], len("HITL crawled content"))
        mock_hitl_crawler.arun.assert_called_once()
        # Check if CrawlerRunConfig was passed, its details are less important for this test focus
        self.assertIsInstance(mock_hitl_crawler.arun.call_args[1]['config'], CrawlerRunConfig)

        self.assertNotIn(session_id, hitl_sessions)
        mock_hitl_crawler.__aexit__.assert_called_once()
        mock_add_docs.assert_called_once() # Ensure data processing path was taken

    async def test_crawl_single_page_with_invalid_hitl_session(self):
        response_str = await crawl_single_page(self.mock_ctx, "http://example.com/page", hitl_session_id="invalid-session")
        response = json.loads(response_str)
        self.assertFalse(response["success"])
        self.assertIn("Invalid or expired HITL session ID", response["error"])

    @patch('src.crawl4ai_mcp.extract_code_blocks', return_value=[])
    @patch('src.crawl4ai_mcp.update_source_info')
    @patch('src.crawl4ai_mcp.extract_source_summary')
    @patch('src.crawl4ai_mcp.add_documents_to_supabase')
    async def test_crawl_single_page_without_hitl(self, mock_add_docs, mock_extract_summary, mock_update_source, mock_extract_code):
        self.mock_global_crawler.arun.return_value = create_mock_crawl_result(markdown="Global crawled content")
        mock_extract_summary.return_value = "Global Summary"

        response_str = await crawl_single_page(self.mock_ctx, "http://example.com/global_page")
        response = json.loads(response_str)

        self.assertTrue(response["success"])
        self.assertEqual(response["content_length"], len("Global crawled content"))
        self.mock_global_crawler.arun.assert_called_once()
        mock_add_docs.assert_called_once()
        self.assertEqual(len(hitl_sessions), 0) # No HITL session should be involved or cleaned up

    @patch('src.crawl4ai_mcp.add_documents_to_supabase') # Mock to prevent actual DB calls
    async def test_crawl_single_page_with_hitl_crawl_exception(self, mock_add_docs):
        session_id = str(uuid.uuid4())
        mock_hitl_crawler = AsyncMock()
        mock_hitl_crawler.arun.side_effect = Exception("Crawling failed!")
        # mock_hitl_crawler.__aexit__ = AsyncMock()

        hitl_sessions[session_id] = mock_hitl_crawler

        response_str = await crawl_single_page(self.mock_ctx, "http://example.com/fail_page", hitl_session_id=session_id)
        response = json.loads(response_str)

        self.assertFalse(response["success"])
        self.assertIn("Crawling failed!", response["error"])
        self.assertNotIn(session_id, hitl_sessions) # Session should be cleaned up even on error
        mock_hitl_crawler.__aexit__.assert_called_once()
        mock_add_docs.assert_not_called() # Data processing should be skipped


    # --- Tests for smart_crawl_url with HITL ---

    @patch('src.crawl4ai_mcp.extract_code_blocks', return_value=[])
    @patch('src.crawl4ai_mcp.update_source_info')
    @patch('src.crawl4ai_mcp.extract_source_summary')
    @patch('src.crawl4ai_mcp.add_documents_to_supabase')
    @patch('src.crawl4ai_mcp.crawl_recursive_internal_links') # Target where it's used
    async def test_smart_crawl_url_with_hitl_success_regular_page(
        self, mock_crawl_recursive, mock_add_docs, mock_extract_summary, mock_update_source, mock_extract_code):

        session_id = str(uuid.uuid4())
        mock_hitl_crawler = AsyncMock(name="HITLCrawlerForSmart")
        # mock_hitl_crawler.__aexit__ = AsyncMock()
        hitl_sessions[session_id] = mock_hitl_crawler

        # Helper function returns a list of dicts
        mock_crawl_recursive.return_value = [{"url": "http://example.com/smart_hitl", "markdown": "Smart HITL content"}]
        mock_extract_summary.return_value = "Smart Summary"

        test_url = "http://example.com/smart_hitl" # Regular page
        response_str = await smart_crawl_url(self.mock_ctx, test_url, hitl_session_id=session_id)
        response = json.loads(response_str)

        self.assertTrue(response["success"])
        self.assertEqual(response["crawl_type"], "webpage")
        self.assertEqual(response["pages_crawled"], 1)
        mock_crawl_recursive.assert_called_once_with(mock_hitl_crawler, [test_url], max_depth=3, max_concurrent=10)
        self.assertNotIn(session_id, hitl_sessions)
        mock_hitl_crawler.__aexit__.assert_called_once()
        mock_add_docs.assert_called_once()

    @patch('src.crawl4ai_mcp.extract_code_blocks', return_value=[])
    @patch('src.crawl4ai_mcp.update_source_info')
    @patch('src.crawl4ai_mcp.extract_source_summary')
    @patch('src.crawl4ai_mcp.add_documents_to_supabase')
    @patch('src.crawl4ai_mcp.parse_sitemap')
    @patch('src.crawl4ai_mcp.crawl_batch')
    async def test_smart_crawl_url_with_hitl_sitemap(
        self, mock_crawl_batch, mock_parse_sitemap, mock_add_docs, mock_extract_summary, mock_update_source, mock_extract_code):
        session_id = str(uuid.uuid4())
        mock_hitl_crawler = AsyncMock(name="HITLCrawlerSitemap")
        hitl_sessions[session_id] = mock_hitl_crawler

        sitemap_url = "http://example.com/sitemap.xml"
        parsed_urls = ["http://example.com/page1", "http://example.com/page2"]
        mock_parse_sitemap.return_value = parsed_urls
        mock_crawl_batch.return_value = [{"url": u, "markdown": f"Content for {u}"} for u in parsed_urls]
        mock_extract_summary.return_value = "Sitemap Summary"

        response_str = await smart_crawl_url(self.mock_ctx, sitemap_url, hitl_session_id=session_id)
        response = json.loads(response_str)

        self.assertTrue(response["success"])
        self.assertEqual(response["crawl_type"], "sitemap")
        mock_parse_sitemap.assert_called_once_with(sitemap_url)
        mock_crawl_batch.assert_called_once_with(mock_hitl_crawler, parsed_urls, max_concurrent=10)
        self.assertNotIn(session_id, hitl_sessions)
        mock_hitl_crawler.__aexit__.assert_called_once()

    @patch('src.crawl4ai_mcp.extract_code_blocks', return_value=[])
    @patch('src.crawl4ai_mcp.update_source_info')
    @patch('src.crawl4ai_mcp.extract_source_summary')
    @patch('src.crawl4ai_mcp.add_documents_to_supabase')
    @patch('src.crawl4ai_mcp.crawl_markdown_file')
    async def test_smart_crawl_url_with_hitl_txt_file(
        self, mock_crawl_txt, mock_add_docs, mock_extract_summary, mock_update_source, mock_extract_code):
        session_id = str(uuid.uuid4())
        mock_hitl_crawler = AsyncMock(name="HITLCrawlerTxt")
        hitl_sessions[session_id] = mock_hitl_crawler

        txt_url = "http://example.com/file.txt"
        mock_crawl_txt.return_value = [{"url": txt_url, "markdown": "Text file content"}]
        mock_extract_summary.return_value = "Txt Summary"

        response_str = await smart_crawl_url(self.mock_ctx, txt_url, hitl_session_id=session_id)
        response = json.loads(response_str)

        self.assertTrue(response["success"])
        self.assertEqual(response["crawl_type"], "text_file")
        mock_crawl_txt.assert_called_once_with(mock_hitl_crawler, txt_url)
        self.assertNotIn(session_id, hitl_sessions)
        mock_hitl_crawler.__aexit__.assert_called_once()

    async def test_smart_crawl_url_with_invalid_hitl_session(self):
        response_str = await smart_crawl_url(self.mock_ctx, "http://example.com/page", hitl_session_id="invalid-session")
        response = json.loads(response_str)
        self.assertFalse(response["success"])
        self.assertIn("Invalid or expired HITL session ID", response["error"])

    @patch('src.crawl4ai_mcp.extract_code_blocks', return_value=[])
    @patch('src.crawl4ai_mcp.update_source_info')
    @patch('src.crawl4ai_mcp.extract_source_summary')
    @patch('src.crawl4ai_mcp.add_documents_to_supabase')
    @patch('src.crawl4ai_mcp.crawl_recursive_internal_links')
    async def test_smart_crawl_url_without_hitl_regular_page(
        self, mock_crawl_recursive, mock_add_docs, mock_extract_summary, mock_update_source, mock_extract_code):

        mock_crawl_recursive.return_value = [{"url": "http://example.com/global_smart", "markdown": "Global Smart Content"}]
        mock_extract_summary.return_value = "Global Smart Summary"
        test_url = "http://example.com/global_smart"

        response_str = await smart_crawl_url(self.mock_ctx, test_url) # No hitl_session_id
        response = json.loads(response_str)

        self.assertTrue(response["success"])
        mock_crawl_recursive.assert_called_once_with(self.mock_global_crawler, [test_url], max_depth=3, max_concurrent=10)
        self.assertEqual(len(hitl_sessions), 0)

    @patch('src.crawl4ai_mcp.add_documents_to_supabase') # Mock to prevent actual DB calls
    @patch('src.crawl4ai_mcp.crawl_recursive_internal_links')
    async def test_smart_crawl_url_with_hitl_helper_exception(self, mock_crawl_recursive, mock_add_docs):
        session_id = str(uuid.uuid4())
        mock_hitl_crawler = AsyncMock(name="HITLCrawlerException")
        # mock_hitl_crawler.__aexit__ = AsyncMock()
        hitl_sessions[session_id] = mock_hitl_crawler

        mock_crawl_recursive.side_effect = Exception("Helper failed!")
        test_url = "http://example.com/smart_fail"

        response_str = await smart_crawl_url(self.mock_ctx, test_url, hitl_session_id=session_id)
        response = json.loads(response_str)

        self.assertFalse(response["success"])
        self.assertIn("Helper failed!", response["error"])
        self.assertNotIn(session_id, hitl_sessions)
        mock_hitl_crawler.__aexit__.assert_called_once()
        mock_add_docs.assert_not_called()

if __name__ == '__main__':
    # This allows running the tests directly from the command line
    unittest.main()
