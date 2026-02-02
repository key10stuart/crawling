# What Is A Website, Really?

When you type `jbhunt.com` into a browser, what actually happens?

## The Journey of a URL

```
You type: jbhunt.com
                │
                ▼
        ┌───────────────┐
        │  DNS Lookup   │  "What IP is jbhunt.com?"
        │  ─────────────│  Answer: 104.18.23.55
        └───────────────┘
                │
                ▼
        ┌───────────────┐
        │  TCP Connect  │  Your computer calls that IP on port 443 (HTTPS)
        └───────────────┘
                │
                ▼
        ┌───────────────┐
        │  TLS Handshake│  Encryption negotiation (the 🔒 in your browser)
        └───────────────┘
                │
                ▼
        ┌───────────────┐
        │  HTTP Request │  GET / HTTP/1.1
        │               │  Host: www.jbhunt.com
        │               │  User-Agent: Mozilla/5.0...
        └───────────────┘
                │
                ▼
        ┌───────────────┐
        │  HTTP Response│  200 OK
        │               │  Content-Type: text/html
        │               │  <html>...</html>
        └───────────────┘
```

## But Wait, There's More

That IP address (104.18.23.55) isn't J.B. Hunt's actual server. It's **Cloudflare** -
a CDN (Content Delivery Network) that sits in front of the real server.

```
You  ──►  Cloudflare (CDN)  ──►  Origin Server (actual website)
          │
          ├─ Caches content
          ├─ Blocks bad bots
          ├─ Stops DDoS attacks
          └─ Serves from nearest datacenter
```

This is why our crawler has a **recon phase** - we need to understand what's
between us and the actual content.

## What's In The HTML?

When you get that HTML response, it's just text:

```html
<!DOCTYPE html>
<html>
<head>
    <title>J.B. Hunt Transport Services</title>
    <link rel="stylesheet" href="/styles.css">
    <script src="/app.js"></script>
</head>
<body>
    <nav>...</nav>
    <main>
        <h1>Driving the Future of Logistics</h1>
        <p>J.B. Hunt is one of the largest...</p>
    </main>
    <footer>...</footer>
</body>
</html>
```

Your browser then:
1. Parses this HTML into a DOM (Document Object Model) tree
2. Fetches the CSS and applies styling
3. Fetches and executes the JavaScript
4. Renders pixels on your screen

## The SPA Problem

Modern websites often look like this instead:

```html
<!DOCTYPE html>
<html>
<head>
    <title>Saia LTL Freight</title>
</head>
<body>
    <app-root></app-root>
    <script src="/main.js"></script>
</body>
</html>
```

That's it. Just an empty `<app-root>` tag and a JavaScript file.

The actual content doesn't exist until JavaScript runs and "hydrates" the page.
This is a **Single Page Application (SPA)** - built with frameworks like:
- Angular (what Saia uses)
- React
- Vue.js

**This is why simple HTTP requests fail on SPAs** - you get the empty shell,
not the rendered content. You need a real browser (like Playwright) to execute
the JavaScript first.

## See It Yourself

```bash
# Simple HTTP request - gets the raw HTML
curl https://www.saia.com

# What you'll see:
# <app-root></app-root>
# <script src="main.js"></script>
# ...that's it, no content!

# With our crawler's recon:
python -c "
from fetch.recon import recon_site
r = recon_site('https://www.saia.com')
print(f'JS Required: {r.js_required}')
print(f'Framework: {r.framework}')
"
# Output:
# JS Required: True
# Framework: angular
```

## The Layers of a Modern Website

```
┌─────────────────────────────────────────────────────────┐
│                    What You See                         │
│              (rendered pixels on screen)                │
└─────────────────────────────────────────────────────────┘
                          ▲
┌─────────────────────────────────────────────────────────┐
│                   Browser Engine                        │
│         (Chrome's Blink, Firefox's Gecko)               │
│    Parses HTML → Builds DOM → Applies CSS → Paints      │
└─────────────────────────────────────────────────────────┘
                          ▲
┌─────────────────────────────────────────────────────────┐
│                    JavaScript                           │
│         (React/Angular/Vue app code)                    │
│    Fetches data, manipulates DOM, handles events        │
└─────────────────────────────────────────────────────────┘
                          ▲
┌─────────────────────────────────────────────────────────┐
│                    Raw HTML/CSS/JS                      │
│              (what the server sends)                    │
└─────────────────────────────────────────────────────────┘
                          ▲
┌─────────────────────────────────────────────────────────┐
│                   CDN / WAF Layer                       │
│          (Cloudflare, Akamai, StackPath)                │
│    Caching, bot detection, DDoS protection              │
└─────────────────────────────────────────────────────────┘
                          ▲
┌─────────────────────────────────────────────────────────┐
│                   Origin Server                         │
│        (the actual web application)                     │
│    Database, business logic, content management         │
└─────────────────────────────────────────────────────────┘
```

## Next: The Arms Race

Why do websites block bots? How do they detect them? And how do we get
through anyway (ethically)?

→ [01_the_arms_race.md](01_the_arms_race.md)
