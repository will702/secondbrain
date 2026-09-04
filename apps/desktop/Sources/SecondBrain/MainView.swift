import SwiftUI
@preconcurrency import WebKit

/// The product surface: the web UI in a native window, same-origin with the
/// API behind it. External links go to the user's default browser.
struct MainView: View {
    let url: URL
    @EnvironmentObject private var state: AppState

    var body: some View {
        WebViewContainer(url: url, pendingPath: $state.pendingPath)
            .ignoresSafeArea(edges: .bottom)
            .background(Color(nsColor: .windowBackgroundColor))
    }
}

private struct WebViewContainer: NSViewRepresentable {
    let url: URL
    @Binding var pendingPath: String?

    func makeNSView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.defaultWebpagePreferences.allowsContentJavaScript = true

        let webView = WKWebView(frame: .zero, configuration: config)
        webView.allowsBackForwardNavigationGestures = true
        webView.navigationDelegate = context.coordinator
        context.coordinator.webView = webView
        webView.load(URLRequest(url: url))
        return webView
    }

    func updateNSView(_ nsView: WKWebView, context: Context) {
        if let path = pendingPath {
            // Menu-bar action (e.g. "Enable AI…") navigates the live webview.
            pendingPath = nil
            var components = URLComponents(url: url, resolvingAgainstBaseURL: false)!
            components.path = path
            if let target = components.url {
                nsView.load(URLRequest(url: target))
            }
            return
        }
        guard let current = nsView.url, current.host == url.host, current.port == url.port else {
            nsView.load(URLRequest(url: url))
            return
        }
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    final class Coordinator: NSObject, WKNavigationDelegate {
        weak var webView: WKWebView?

        func webView(
            _ webView: WKWebView,
            decidePolicyFor navigationAction: WKNavigationAction,
            decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
        ) {
            guard let url = navigationAction.request.url,
                  let scheme = url.scheme?.lowercased(),
                  scheme == "http" || scheme == "https"
            else {
                decisionHandler(.cancel)
                return
            }
            // Same-origin app navigations stay in the window; anything else
            // (target=_blank, external hosts like OAuth) → default browser.
            let isAppOrigin = url.host == "127.0.0.1" || url.host == "localhost"
            if isAppOrigin, navigationAction.targetFrame?.isMainFrame != false {
                decisionHandler(.allow)
            } else {
                NSWorkspace.shared.open(url)
                decisionHandler(.cancel)
            }
        }

        func webView(
            _ webView: WKWebView,
            didFailProvisionalNavigation navigation: WKNavigation!,
            withError error: Error
        ) {
            // Backend likely restarted or is briefly unavailable — reload once
            // the server answers again.
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { [weak webView] in
                webView?.reload()
            }
        }
    }
}
