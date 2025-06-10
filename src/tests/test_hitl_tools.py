import unittest
from unittest.mock import patch, AsyncMock, MagicMock, PropertyMock
import json
import uuid
import os # Added for os.environ patching
import asyncio # Added for asyncio.iscoroutinefunction check

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
)
from crawl4ai import CrawlerRunConfig, BrowserConfig # For type hinting and BrowserConfig assertions
from pyvirtualdisplay import Display # For spec in mocking Display

# AsyncWebCrawler and BrowserConfig are imported in crawl4ai_mcp, so we patch them there.
# Display will also be patched there.

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
        # Clean up any environment variables patched by tests
        for var in ["APP_EXTERNAL_HOSTNAME", "NOVNC_PORT", "VNC_PORT"]:
            if var in os.environ:
                del os.environ[var]

    @patch('src.crawl4ai_mcp.Display')
    @patch('src.crawl4ai_mcp.BrowserConfig')
    @patch('src.crawl4ai_mcp.AsyncWebCrawler')
    @patch.dict(os.environ, {}, clear=True) # Ensure clean env for default test
    async def test_initiate_vnc_success_default_host(self, MockAsyncWebCrawler, MockBrowserConfig, MockDisplay):
        """Test successful VNC HITL initiation with default hostname and ports."""
        mock_display_instance = MagicMock(spec=Display)
        mock_display_instance.rfbport = 5901 # Simulate default rfbport
        mock_display_instance.display = ":1" # Simulate a display name
        MockDisplay.return_value = mock_display_instance

        mock_crawler_instance = AsyncMock()
        MockAsyncWebCrawler.return_value = mock_crawler_instance

        mock_browser_config_instance = MagicMock(spec=BrowserConfig)
        MockBrowserConfig.return_value = mock_browser_config_instance

        target_url = "http://example.com"
        response_str = await initiate_human_in_the_loop(self.mock_ctx, target_url)
        response = json.loads(response_str)

        self.assertTrue(response["success"], f"Response error: {response.get('error')}")
        self.assertIn("session_id", response)
        self.assertIn("novnc_url", response)
        self.assertEqual(response["novnc_url"], "http://localhost:6080/vnc.html") # Defaults

        session_id = response["session_id"]
        self.assertIn(session_id, hitl_sessions)
        self.assertIsInstance(hitl_sessions[session_id], dict)
        self.assertEqual(hitl_sessions[session_id]['crawler'], mock_crawler_instance)
        self.assertEqual(hitl_sessions[session_id]['display'], mock_display_instance)
        self.assertEqual(hitl_sessions[session_id]['vnc_port'], 5901)

        MockDisplay.assert_called_once_with(
            backend="xvnc", rfbport=5901, size=(1280, 1024), color_depth=24
        )
        mock_display_instance.start.assert_called_once()
        mock_crawler_instance.__aenter__.assert_called_once()
        MockBrowserConfig.assert_called_once_with(
            headless=False,
            browser_args=["--no-sandbox", "--disable-gpu", "--window-size=1280,1024"],
            verbose=True
        )
        MockAsyncWebCrawler.assert_called_once_with(config=mock_browser_config_instance)

        # Cleanup for this test (as initiate doesn't cleanup on success)
        hitl_sessions[session_id]['display'].stop() # Stop the display
        await hitl_sessions[session_id]['crawler'].__aexit__(None, None, None) # Stop crawler
        del hitl_sessions[session_id]


    @patch('src.crawl4ai_mcp.Display')
    @patch('src.crawl4ai_mcp.BrowserConfig')
    @patch('src.crawl4ai_mcp.AsyncWebCrawler')
    async def test_initiate_vnc_success_custom_host(self, MockAsyncWebCrawler, MockBrowserConfig, MockDisplay):
        """Test VNC HITL initiation with custom hostname and ports."""
        custom_env = {
            "APP_EXTERNAL_HOSTNAME": "custom.host",
            "NOVNC_PORT": "7000",
            "VNC_PORT": "6001"
        }
        with patch.dict(os.environ, custom_env, clear=True):
            mock_display_instance = MagicMock(spec=Display)
            mock_display_instance.rfbport = 6001
            mock_display_instance.display = ":2"
            MockDisplay.return_value = mock_display_instance

            mock_crawler_instance = AsyncMock()
            MockAsyncWebCrawler.return_value = mock_crawler_instance
            MockBrowserConfig.return_value = MagicMock(spec=BrowserConfig)

            response_str = await initiate_human_in_the_loop(self.mock_ctx, "http://example.com")
            response = json.loads(response_str)

            self.assertTrue(response["success"])
            self.assertEqual(response["novnc_url"], "http://custom.host:7000/vnc.html")
            session_id = response["session_id"]
            self.assertEqual(hitl_sessions[session_id]['vnc_port'], 6001)
            MockDisplay.assert_called_once_with(
                backend="xvnc", rfbport=6001, size=(1280, 1024), color_depth=24
            )
            # Cleanup
            hitl_sessions[session_id]['display'].stop()
            await hitl_sessions[session_id]['crawler'].__aexit__(None, None, None)
            del hitl_sessions[session_id]


    @patch('src.crawl4ai_mcp.Display')
    @patch('src.crawl4ai_mcp.BrowserConfig') # Still needed as it's imported
    @patch('src.crawl4ai_mcp.AsyncWebCrawler') # Still needed
    async def test_initiate_vnc_display_start_failure(self, MockAsyncWebCrawler, MockBrowserConfig, MockDisplay):
        """Test VNC HITL initiation fails if Display.start() raises an exception."""
        mock_display_instance = MagicMock(spec=Display)
        mock_display_instance.start.side_effect = Exception("Display start failed")
        MockDisplay.return_value = mock_display_instance

        response_str = await initiate_human_in_the_loop(self.mock_ctx, "http://example.com")
        response = json.loads(response_str)

        self.assertFalse(response["success"])
        self.assertIn("Failed to initiate HITL VNC session: Display start failed", response["error"])
        self.assertEqual(len(hitl_sessions), 0)
        mock_display_instance.start.assert_called_once()
        # stop() should not be called if start() failed, but the code calls is_alive then stop
        # if disp.is_alive() is True (mocked default), then stop() might be called.
        # Let's ensure is_alive is False if start fails for a cleaner test
        mock_display_instance.is_alive.return_value = False
        mock_display_instance.stop.assert_not_called()


    @patch('src.crawl4ai_mcp.Display')
    @patch('src.crawl4ai_mcp.BrowserConfig')
    @patch('src.crawl4ai_mcp.AsyncWebCrawler')
    async def test_initiate_browser_launch_exception_vnc(self, MockAsyncWebCrawler, MockBrowserConfig, MockDisplay):
        """Test VNC HITL when browser launch fails after display starts."""
        mock_display_instance = MagicMock(spec=Display)
        mock_display_instance.rfbport = 5901
        mock_display_instance.display = ":1"
        mock_display_instance.is_alive.return_value = True # Start succeeded
        MockDisplay.return_value = mock_display_instance

        mock_crawler_instance = AsyncMock()
        mock_crawler_instance.__aenter__.side_effect = Exception("Browser launch failed")
        MockAsyncWebCrawler.return_value = mock_crawler_instance
        MockBrowserConfig.return_value = MagicMock(spec=BrowserConfig)

        response_str = await initiate_human_in_the_loop(self.mock_ctx, "http://example.com")
        response = json.loads(response_str)

        self.assertFalse(response["success"])
        self.assertIn("Failed to initiate HITL VNC session: Browser launch failed", response["error"])
        self.assertEqual(len(hitl_sessions), 0)

        mock_display_instance.start.assert_called_once()
        mock_crawler_instance.__aenter__.assert_called_once()
        mock_display_instance.stop.assert_called_once() # Display should be stopped


    async def test_resume_success(self):
        """Test successful resumption of a valid HITL session."""
        session_id = str(uuid.uuid4())
        # For resume, the content of the session dict doesn't matter as much, just its existence.
        hitl_sessions[session_id] = {'crawler': MagicMock(), 'display': MagicMock()}

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

    @patch('src.crawl4ai_mcp.Display')
    @patch('src.crawl4ai_mcp.BrowserConfig')
    @patch('src.crawl4ai_mcp.AsyncWebCrawler')
    @patch.dict(os.environ, {}, clear=True)
    async def test_initiate_navigation_attempt_vnc(self, MockAsyncWebCrawler, MockBrowserConfig, MockDisplay):
        """Test that navigation is attempted during successful VNC HITL initiation."""
        mock_display_instance = MagicMock(spec=Display)
        mock_display_instance.rfbport = 5901
        mock_display_instance.display = ":1"
        MockDisplay.return_value = mock_display_instance

        mock_crawler_instance = AsyncMock()
        mock_page = AsyncMock()
        mock_crawler_instance.page = mock_page # Assume .page attribute for navigation
        MockAsyncWebCrawler.return_value = mock_crawler_instance

        MockBrowserConfig.return_value = MagicMock(spec=BrowserConfig)

        target_url = "http://example.com/navigate"
        response_str = await initiate_human_in_the_loop(self.mock_ctx, target_url)
        response = json.loads(response_str)

        self.assertTrue(response["success"])
        session_id = response["session_id"]

        mock_display_instance.start.assert_called_once()
        mock_crawler_instance.__aenter__.assert_called_once()
        mock_crawler_instance.page.goto.assert_called_once_with(target_url, timeout=60000)

        # Cleanup
        if session_id in hitl_sessions:
            session_data = hitl_sessions.pop(session_id, None)
            if session_data:
                session_data['display'].stop()
                await session_data['crawler'].__aexit__(None, None, None)


    # --- Tests for crawl_single_page with HITL ---

    @patch('src.crawl4ai_mcp.extract_code_blocks', return_value=[])
    @patch('src.crawl4ai_mcp.update_source_info')
    @patch('src.crawl4ai_mcp.extract_source_summary')
    @patch('src.crawl4ai_mcp.add_documents_to_supabase')
    async def test_crawl_single_page_with_hitl_success(self, mock_add_docs, mock_extract_summary, mock_update_source, mock_extract_code):
        session_id = str(uuid.uuid4())
        mock_hitl_crawler = AsyncMock(spec=True)
        mock_hitl_crawler.arun.return_value = create_mock_crawl_result(markdown="HITL crawled content")

        mock_display_instance = MagicMock(spec=Display)
        mock_display_instance.is_alive.return_value = True
        hitl_sessions[session_id] = {'crawler': mock_hitl_crawler, 'display': mock_display_instance, 'vnc_port': 5901}

        mock_extract_summary.return_value = "Summary"

        response_str = await crawl_single_page(self.mock_ctx, "http://example.com/hitl_page", hitl_session_id=session_id)
        response = json.loads(response_str)

        self.assertTrue(response["success"])
        self.assertEqual(response["content_length"], len("HITL crawled content"))
        mock_hitl_crawler.arun.assert_called_once()
        self.assertIsInstance(mock_hitl_crawler.arun.call_args[1]['config'], CrawlerRunConfig)

        self.assertNotIn(session_id, hitl_sessions)
        mock_hitl_crawler.__aexit__.assert_called_once()
        mock_display_instance.stop.assert_called_once() # Verify display is stopped
        mock_add_docs.assert_called_once()

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
        self.assertEqual(len(hitl_sessions), 0)

    @patch('src.crawl4ai_mcp.add_documents_to_supabase')
    async def test_crawl_single_page_with_hitl_crawl_exception(self, mock_add_docs):
        session_id = str(uuid.uuid4())
        mock_hitl_crawler = AsyncMock(spec=True)
        mock_hitl_crawler.arun.side_effect = Exception("Crawling failed!")

        mock_display_instance = MagicMock(spec=Display)
        mock_display_instance.is_alive.return_value = True
        hitl_sessions[session_id] = {'crawler': mock_hitl_crawler, 'display': mock_display_instance}

        response_str = await crawl_single_page(self.mock_ctx, "http://example.com/fail_page", hitl_session_id=session_id)
        response = json.loads(response_str)

        self.assertFalse(response["success"])
        self.assertIn("Crawling failed!", response["error"])
        self.assertNotIn(session_id, hitl_sessions)
        mock_hitl_crawler.__aexit__.assert_called_once()
        mock_display_instance.stop.assert_called_once()
        mock_add_docs.assert_not_called()


    # --- Tests for smart_crawl_url with HITL ---

    @patch('src.crawl4ai_mcp.extract_code_blocks', return_value=[])
    @patch('src.crawl4ai_mcp.update_source_info')
    @patch('src.crawl4ai_mcp.extract_source_summary')
    @patch('src.crawl4ai_mcp.add_documents_to_supabase')
    @patch('src.crawl4ai_mcp.crawl_recursive_internal_links')
    async def test_smart_crawl_url_with_hitl_success_regular_page(
        self, mock_crawl_recursive, mock_add_docs, mock_extract_summary, mock_update_source, mock_extract_code):

        session_id = str(uuid.uuid4())
        mock_hitl_crawler = AsyncMock(name="HITLCrawlerForSmart", spec=True)
        mock_display_instance = MagicMock(spec=Display)
        mock_display_instance.is_alive.return_value = True
        hitl_sessions[session_id] = {'crawler': mock_hitl_crawler, 'display': mock_display_instance}

        mock_crawl_recursive.return_value = [{"url": "http://example.com/smart_hitl", "markdown": "Smart HITL content"}]
        mock_extract_summary.return_value = "Smart Summary"
        test_url = "http://example.com/smart_hitl"

        response_str = await smart_crawl_url(self.mock_ctx, test_url, hitl_session_id=session_id)
        response = json.loads(response_str)

        self.assertTrue(response["success"])
        self.assertEqual(response["crawl_type"], "webpage")
        mock_crawl_recursive.assert_called_once_with(mock_hitl_crawler, [test_url], max_depth=3, max_concurrent=10)
        self.assertNotIn(session_id, hitl_sessions)
        mock_hitl_crawler.__aexit__.assert_called_once()
        mock_display_instance.stop.assert_called_once()
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
        mock_hitl_crawler = AsyncMock(name="HITLCrawlerSitemap", spec=True)
        mock_display_instance = MagicMock(spec=Display)
        mock_display_instance.is_alive.return_value = True
        hitl_sessions[session_id] = {'crawler': mock_hitl_crawler, 'display': mock_display_instance}

        sitemap_url = "http://example.com/sitemap.xml"
        parsed_urls = ["http://example.com/page1"]
        mock_parse_sitemap.return_value = parsed_urls
        mock_crawl_batch.return_value = [{"url": u, "markdown": f"Content for {u}"} for u in parsed_urls]
        mock_extract_summary.return_value = "Sitemap Summary"

        response_str = await smart_crawl_url(self.mock_ctx, sitemap_url, hitl_session_id=session_id)
        response = json.loads(response_str)

        self.assertTrue(response["success"])
        mock_crawl_batch.assert_called_once_with(mock_hitl_crawler, parsed_urls, max_concurrent=10)
        self.assertNotIn(session_id, hitl_sessions)
        mock_hitl_crawler.__aexit__.assert_called_once()
        mock_display_instance.stop.assert_called_once()

    @patch('src.crawl4ai_mcp.extract_code_blocks', return_value=[])
    @patch('src.crawl4ai_mcp.update_source_info')
    @patch('src.crawl4ai_mcp.extract_source_summary')
    @patch('src.crawl4ai_mcp.add_documents_to_supabase')
    @patch('src.crawl4ai_mcp.crawl_markdown_file')
    async def test_smart_crawl_url_with_hitl_txt_file(
        self, mock_crawl_txt, mock_add_docs, mock_extract_summary, mock_update_source, mock_extract_code):
        session_id = str(uuid.uuid4())
        mock_hitl_crawler = AsyncMock(name="HITLCrawlerTxt", spec=True)
        mock_display_instance = MagicMock(spec=Display)
        mock_display_instance.is_alive.return_value = True
        hitl_sessions[session_id] = {'crawler': mock_hitl_crawler, 'display': mock_display_instance}

        txt_url = "http://example.com/file.txt"
        mock_crawl_txt.return_value = [{"url": txt_url, "markdown": "Text file content"}]
        mock_extract_summary.return_value = "Txt Summary"

        response_str = await smart_crawl_url(self.mock_ctx, txt_url, hitl_session_id=session_id)
        response = json.loads(response_str)

        self.assertTrue(response["success"])
        mock_crawl_txt.assert_called_once_with(mock_hitl_crawler, txt_url)
        self.assertNotIn(session_id, hitl_sessions)
        mock_hitl_crawler.__aexit__.assert_called_once()
        mock_display_instance.stop.assert_called_once()

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

    @patch('src.crawl4ai_mcp.add_documents_to_supabase')
    @patch('src.crawl4ai_mcp.crawl_recursive_internal_links')
    async def test_smart_crawl_url_with_hitl_helper_exception(self, mock_crawl_recursive, mock_add_docs):
        session_id = str(uuid.uuid4())
        mock_hitl_crawler = AsyncMock(name="HITLCrawlerException", spec=True)
        mock_display_instance = MagicMock(spec=Display)
        mock_display_instance.is_alive.return_value = True
        hitl_sessions[session_id] = {'crawler': mock_hitl_crawler, 'display': mock_display_instance}

        mock_crawl_recursive.side_effect = Exception("Helper failed!")
        test_url = "http://example.com/smart_fail"

        response_str = await smart_crawl_url(self.mock_ctx, test_url, hitl_session_id=session_id)
        response = json.loads(response_str)

        self.assertFalse(response["success"])
        self.assertIn("Helper failed!", response["error"])
        self.assertNotIn(session_id, hitl_sessions)
        mock_hitl_crawler.__aexit__.assert_called_once()
        mock_display_instance.stop.assert_called_once()
        mock_add_docs.assert_not_called()

if __name__ == '__main__':
    # This allows running the tests directly from the command line
    unittest.main()
