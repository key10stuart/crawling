import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

FLOW_PATH = Path("monkey.flow.json")

async def record_interactions():
    interactions = []
    session_active = True

    async def input_listener():
        nonlocal session_active
        await asyncio.get_event_loop().run_in_executor(None, input)
        print("👋 Exit requested via keyboard input.")
        session_active = False

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()

        # Set URL manually or via pull_run.json logic later
        start_url = "https://example.com"
        await page.goto(start_url)

        # Expose binding so JS can call Python
        async def report_click(data):
            selector = data.get("selector")
            meta = data.get("meta", {})
            if not selector:
                print(f"⚠️ Empty selector received — fallback: {meta}")
            else:
                print(f"🖱 Click recorded: {selector}")
            interactions.append({"action": "click", "selector": selector, "meta": meta})

        await page.expose_binding("reportClick", lambda _, data: asyncio.create_task(report_click(data)))

        # Record GET/POST requests
        page.on("request", lambda request: interactions.append({
            "action": "request",
            "method": request.method,
            "url": request.url
        }))

        # Track downloads
        page.on("download", lambda download: interactions.append({
            "action": "download",
            "url": download.url,
            "suggested_filename": download.suggested_filename
        }))

        # Log navigation actions
        def log_navigation(target_page):
            interactions.append({"action": "navigate", "url": target_page.url})
            print(f"🌐 Navigated to: {target_page.url}")

        page.on("framenavigated", lambda frame: log_navigation(page))

        # Track active tab switching
        def track_active_page(new_active_page):
            print(f"📄 Switched to new tab: {new_active_page.url}")
            interactions.append({
                "action": "switch_tab",
                "url": new_active_page.url
            })

        context.on("page", lambda new_page: new_page.once("domcontentloaded", lambda: track_active_page(new_page)))

        # Define JS injection logic
        async def inject_click_listener(target_page):
            await target_page.evaluate("""
                () => {
                    if (!document.body) return;

                    const hud = document.getElementById("monkey_hud");
                    if (!hud) {
                        const div = document.createElement("div");
                        div.id = "monkey_hud";
                        div.innerHTML = "👁️ monkey_see active";
                        div.style.cssText = "position:fixed;top:10px;left:10px;z-index:9999;background:black;color:white;padding:5px;font-size:12px;";
                        document.body.appendChild(div);
                    }

                    document.addEventListener("click", event => {
                        let path = event.composedPath().find(e =>
                          e instanceof HTMLElement &&
                          e.tagName.toLowerCase() !== 'html' &&
                          e.tagName.toLowerCase() !== 'body'
                        );
                        if (path) {
                            try {
                                const selector = generateUniqueSelector(path);
                                const meta = {
                                    tagName: path.tagName,
                                    id: path.id,
                                    class: path.className,
                                    outerHTML: path.outerHTML.slice(0, 500)
                                };
                                window.reportClick({ selector, meta });
                            } catch (err) {
                                console.log('💥 Selector generation failed:', err);
                            }
                        }
                    }, true);

                    function generateUniqueSelector(el) {
                        if (!el || !el.tagName) return "";
                        let path = [];
                        while (el.parentElement) {
                            let name = el.tagName.toLowerCase();
                            if (el.id) {
                                name += `#${el.id}`;
                                path.unshift(name);
                                break;
                            } else {
                                let sibs = Array.from(el.parentElement.children).filter(e => e.tagName === el.tagName);
                                if (sibs.length > 1) {
                                    name += `:nth-child(${[...el.parentElement.children].indexOf(el)+1})`;
                                }
                                path.unshift(name);
                            }
                            el = el.parentElement;
                        }
                        return path.join(" > ");
                    }
                }
            """)

        # Inject into initial page
        await inject_click_listener(page)

        # Rebind on navigation within same tab
        page.on("framenavigated", lambda frame: asyncio.create_task(inject_click_listener(page)))

        # Bind to new tabs and re-inject listeners
        context.on("page", lambda new_page: asyncio.create_task(inject_click_listener(new_page)))

        print("👀 monkey_see is watching — interact with the browser.")
        print("⏎ Press ENTER in terminal to end session early.")

        await asyncio.gather(
            input_listener(),
            monitor_session(lambda: session_active)
        )

        print(f"💾 Saving interactions to {FLOW_PATH}")
        FLOW_PATH.write_text(json.dumps(interactions, indent=2))
        await browser.close()

async def monitor_session(is_active_fn):
    while is_active_fn():
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(record_interactions())
