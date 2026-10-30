package com.citymemory.app

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.app.AlertDialog
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.ActivityNotFoundException
import android.content.ContentValues
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.MediaStore
import android.speech.RecognizerIntent
import android.speech.tts.TextToSpeech
import android.text.InputType
import android.text.TextUtils
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.webkit.JavascriptInterface
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ProgressBar
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.Locale

/**
 * City Memory for Android.
 *
 * The screens come from the City Memory server (the same FastAPI backend as the website, at /m),
 * so the app and the website always show the same live data. This activity adds what a phone app
 * needs on top: the server address, GPS location, camera/gallery photos, voice typing in Kannada,
 * English or Hindi, the back button, and a friendly screen when the server cannot be reached.
 */
class MainActivity : Activity() {

    private lateinit var webView: WebView
    private lateinit var loadingBar: ProgressBar
    private val prefs by lazy { getSharedPreferences("citymemory", MODE_PRIVATE) }
    private val main = Handler(Looper.getMainLooper())

    private var fileCallback: ValueCallback<Array<Uri>>? = null
    private var cameraUri: Uri? = null
    private var pendingLocation = false
    private var clearHistoryAfterLoad = false
    private var openHash: String? = null          // screen to open, e.g. from a danger notification

    // read aloud
    private var tts: TextToSpeech? = null
    private var ttsReady = false
    private var pendingSpeech: Triple<String, String, String>? = null

    // danger alerts for engineers: check the server every 20 seconds while the app is alive
    private val dangerCheck = object : Runnable {
        override fun run() {
            if (prefs.getBoolean(KEY_ENGINEER, false)) checkDanger()
            main.postDelayed(this, 20_000)
        }
    }

    companion object {
        private const val REQ_FILE = 11
        private const val REQ_VOICE = 12
        private const val REQ_LOCATION = 13
        private const val REQ_NOTIFY = 14
        private const val CHANNEL_DANGER = "danger"
        private const val KEY_ENGINEER = "engineer"
        private const val KEY_SEEN_DANGER = "seen_danger"
        private const val DEFAULT_PORT = 8000
        private const val EMULATOR_URL = "http://10.0.2.2:8000"
        private const val KEY_SERVER = "server"
    }

    // ---------------------------------------------------------------- setup

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val root = FrameLayout(this)
        webView = WebView(this)
        loadingBar = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply {
            isIndeterminate = true
            visibility = View.GONE
        }
        root.addView(webView, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        root.addView(loadingBar, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(6), Gravity.TOP))
        setContentView(root)

        val settings = webView.settings
        settings.javaScriptEnabled = true
        settings.domStorageEnabled = true          // remembers language, role and "my complaints" on the phone
        settings.setSupportZoom(false)
        settings.builtInZoomControls = false
        settings.userAgentString = settings.userAgentString + " CityMemoryApp/" + getString(R.string.app_version)

        webView.addJavascriptInterface(Bridge(), "CMNative")
        webView.webViewClient = Client()
        webView.webChromeClient = Chrome()
        WebView.setWebContentsDebuggingEnabled(true)  // inspect from Chrome on the laptop: chrome://inspect

        createDangerChannel()
        openHash = intent?.getStringExtra("open")
        val restored = savedInstanceState != null && webView.restoreState(savedInstanceState) != null
        if (!restored) {
            if (serverUrl().isEmpty()) askServer(first = true) else loadApp()
        }
        main.postDelayed(dangerCheck, 5_000)
    }

    /** A danger notification was tapped while the app was already open. */
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        val hash = intent.getStringExtra("open") ?: return
        webView.evaluateJavascript("location.hash = ${quote(hash)}", null)
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        webView.saveState(outState)
    }

    override fun onResume() {
        super.onResume()
        webView.onResume()
    }

    override fun onPause() {
        webView.onPause()
        super.onPause()
    }

    override fun onDestroy() {
        main.removeCallbacks(dangerCheck)
        tts?.shutdown()
        webView.destroy()
        super.onDestroy()
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (webView.canGoBack()) webView.goBack() else super.onBackPressed()
    }

    private fun dp(v: Int): Int = (v * resources.displayMetrics.density).toInt()

    // ---------------------------------------------------------------- server address

    private fun serverUrl(): String = prefs.getString(KEY_SERVER, "") ?: ""

    /** "192.168.1.10" -> "http://192.168.1.10:8000" */
    private fun normalize(raw: String): String {
        var s = raw.trim().trimEnd('/')
        if (s.endsWith("/m")) s = s.dropLast(2)
        if (s.isEmpty()) return ""
        if (!s.startsWith("http://") && !s.startsWith("https://")) s = "http://$s"
        val uri = Uri.parse(s)
        if (uri.host.isNullOrEmpty()) return ""
        if (uri.port == -1 && uri.scheme == "http") s = "$s:$DEFAULT_PORT"
        return s
    }

    private fun loadApp() {
        clearHistoryAfterLoad = true
        val hash = openHash ?: ""
        openHash = null
        webView.loadUrl(serverUrl() + "/m" + hash)
    }

    private fun askServer(first: Boolean) {
        val input = EditText(this).apply {
            setText(serverUrl().ifEmpty { "http://192.168.1.10:8000" })
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            setSingleLine()
            setSelectAllOnFocus(true)
        }
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(4), dp(20), 0)
            addView(input)
        }
        val builder = AlertDialog.Builder(this)
            .setTitle(R.string.server_title)
            .setMessage(R.string.server_help)
            .setView(box)
            .setCancelable(!first)
            .setPositiveButton(R.string.connect) { _, _ ->
                val url = normalize(input.text.toString())
                if (url.isEmpty()) {
                    askServer(first)
                } else {
                    prefs.edit().putString(KEY_SERVER, url).apply()
                    loadApp()
                }
            }
            .setNeutralButton(R.string.use_emulator) { _, _ ->
                prefs.edit().putString(KEY_SERVER, EMULATOR_URL).apply()
                loadApp()
            }
        if (!first) builder.setNegativeButton(android.R.string.cancel, null)
        builder.show()
    }

    /** Shown when the server cannot be reached (wrong address, laptop off, different Wi-Fi). */
    private fun showOffline(detail: String) {
        val server = TextUtils.htmlEncode(serverUrl())
        val why = TextUtils.htmlEncode(detail)
        val html = """
            <!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
            <style>
              body{margin:0;font-family:sans-serif;background:#F3F6F7;color:#18232E;padding:28px 22px}
              h1{font-size:24px;margin:18px 0 8px} p{line-height:1.45;color:#3A4A57;margin:0 0 10px}
              .box{background:#fff;border:1px solid #E3E9EC;border-radius:16px;padding:14px 16px;margin:16px 0}
              li{margin:6px 0;color:#3A4A57} code{background:#E9EEF1;padding:2px 6px;border-radius:6px}
              button{display:block;width:100%;padding:15px;border-radius:14px;font-size:17px;font-weight:600;margin-top:12px}
              .dark{background:#18232E;color:#fff;border:0} .light{background:#fff;color:#18232E;border:1px solid #D3DCE1}
              .kerb{height:8px;border-radius:4px;background:repeating-linear-gradient(-45deg,#F2C200 0 6px,#18232E 6px 12px)}
            </style></head><body>
            <div class="kerb"></div>
            <h1>Can't reach the City Memory server</h1>
            <p>ಸರ್ವರ್ ಸಿಗಲಿಲ್ಲ · सर्वर से संपर्क नहीं हुआ</p>
            <div class="box"><p>Trying: <code>$server</code></p><p style="font-size:13px">$why</p></div>
            <ol>
              <li>Is <code>run.py</code> running on the laptop?</li>
              <li>Are the phone and laptop on the same Wi-Fi or hotspot?</li>
              <li>Is the address the laptop's IP, like <code>http://192.168.1.10:8000</code>?</li>
            </ol>
            <button class="dark" onclick="CMNative.retry()">Try again</button>
            <button class="light" onclick="CMNative.openSettings()">Change server address</button>
            </body></html>
        """.trimIndent()
        webView.loadDataWithBaseURL(null, html, "text/html", "utf-8", null)
    }

    // ---------------------------------------------------------------- talking to the page

    private fun js(code: String) {
        main.post { webView.evaluateJavascript(code, null) }
    }

    private fun quote(s: String): String = JSONObject.quote(s)

    /** Methods the page can call as window.CMNative.xxx() */
    private inner class Bridge {
        @JavascriptInterface
        fun requestLocation() {
            main.post { startLocation() }
        }

        @JavascriptInterface
        fun startVoice(languageTag: String?) {
            main.post { launchVoice(languageTag ?: "en-IN") }
        }

        @JavascriptInterface
        fun openSettings() {
            main.post { askServer(first = false) }
        }

        @JavascriptInterface
        fun retry() {
            main.post { loadApp() }
        }

        @JavascriptInterface
        fun appVersion(): String = getString(R.string.app_version)

        /** The page says whether this phone is used by an engineer (gets danger notifications). */
        @JavascriptInterface
        fun setEngineer(on: Boolean) {
            main.post {
                prefs.edit().putBoolean(KEY_ENGINEER, on).apply()
                if (on) {
                    askNotificationPermission()
                    checkDanger()
                }
            }
        }

        /** Read text aloud. Uses English if the phone has no voice for that language. */
        @JavascriptInterface
        fun speak(text: String?, languageTag: String?, englishText: String?) {
            val t = text ?: return
            main.post { speakNow(t, languageTag ?: "en-IN", englishText ?: t) }
        }

        @JavascriptInterface
        fun stopSpeaking() {
            main.post { tts?.stop() }
        }
    }

    // ---------------------------------------------------------------- read aloud

    private fun speakNow(text: String, languageTag: String, englishText: String) {
        val engine = tts
        if (engine == null) {
            pendingSpeech = Triple(text, languageTag, englishText)
            tts = TextToSpeech(this) { status ->
                ttsReady = status == TextToSpeech.SUCCESS
                val waiting = pendingSpeech
                pendingSpeech = null
                if (ttsReady && waiting != null) main.post { speakNow(waiting.first, waiting.second, waiting.third) }
            }
            return
        }
        if (!ttsReady) {
            pendingSpeech = Triple(text, languageTag, englishText)
            return
        }
        val result = engine.setLanguage(Locale.forLanguageTag(languageTag))
        if (result == TextToSpeech.LANG_MISSING_DATA || result == TextToSpeech.LANG_NOT_SUPPORTED) {
            engine.setLanguage(Locale.forLanguageTag("en-IN"))
            engine.speak(englishText, TextToSpeech.QUEUE_FLUSH, null, "citymemory")
            js("window.cmOnSpeakFallback && window.cmOnSpeakFallback()")
        } else {
            engine.speak(text, TextToSpeech.QUEUE_FLUSH, null, "citymemory")
        }
    }

    // ---------------------------------------------------------------- danger notifications (engineers)

    private fun createDangerChannel() {
        val channel = NotificationChannel(CHANNEL_DANGER, "Danger alerts", NotificationManager.IMPORTANCE_HIGH).apply {
            description = "Open manholes, live wires and other dangers reported by citizens"
        }
        getSystemService(NotificationManager::class.java)?.createNotificationChannel(channel)
    }

    private fun askNotificationPermission() {
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), REQ_NOTIFY)
        }
    }

    /** Ask the server for open danger reports; notify about any this phone has not seen yet. */
    private fun checkDanger() {
        val base = serverUrl()
        if (base.isEmpty()) return
        Thread {
            try {
                val conn = URL("$base/api/today").openConnection() as HttpURLConnection
                conn.connectTimeout = 5_000
                conn.readTimeout = 8_000
                val body = conn.inputStream.bufferedReader().use { it.readText() }
                conn.disconnect()
                val json = JSONObject(body)
                val dataset = json.optString("dataset")
                val urgent = json.optJSONArray("urgent") ?: return@Thread
                val seen = (prefs.getStringSet(KEY_SEEN_DANGER, emptySet()) ?: emptySet()).toMutableSet()
                val firstCheck = !prefs.getBoolean("danger_started", false)
                for (i in 0 until urgent.length()) {
                    val u = urgent.getJSONObject(i)
                    val id = u.optString("complaint_id")
                    if (id.isEmpty() || !seen.add("$dataset/$id")) continue
                    if (!firstCheck) {   // the very first check only remembers what is already open
                        val hazard = u.optString("hazard")
                        val asset = u.optString("asset_id")
                        main.post { showDanger(id, hazard, asset) }
                    }
                }
                prefs.edit().putStringSet(KEY_SEEN_DANGER, seen).putBoolean("danger_started", true).apply()
            } catch (e: Exception) {
                // server not reachable right now; try again on the next check
            }
        }.start()
    }

    private fun showDanger(complaintId: String, hazard: String, assetId: String) {
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) return
        val what = when (hazard) {
            "manhole" -> "Open manhole"
            "wire" -> "Live or fallen wire"
            "flood" -> "Deep water on the road"
            "tree" -> "Fallen tree"
            else -> "Danger"
        }
        val open = Intent(this, MainActivity::class.java)
            .putExtra("open", "#/e/today")
            .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        val tap = PendingIntent.getActivity(
            this, complaintId.hashCode(), open,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        val place = if (assetId.isNotEmpty() && assetId != "null") "near $assetId" else "at a new place"
        val note = Notification.Builder(this, CHANNEL_DANGER)
            .setSmallIcon(R.drawable.ic_notify_danger)
            .setContentTitle("DANGER: $what")
            .setContentText("Reported by a citizen $place ($complaintId). Tap to open.")
            .setCategory(Notification.CATEGORY_ALARM)
            .setAutoCancel(true)
            .setContentIntent(tap)
            .build()
        getSystemService(NotificationManager::class.java)?.notify(complaintId.hashCode(), note)
    }

    private inner class Client : WebViewClient() {
        override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
            val url = request.url
            val server = Uri.parse(serverUrl())
            val sameServer = (url.scheme == "http" || url.scheme == "https") &&
                url.host == server.host && url.port == server.port
            if (sameServer) return false
            // other links (e.g. the map credits) open in the phone's browser
            try {
                startActivity(Intent(Intent.ACTION_VIEW, url))
            } catch (e: ActivityNotFoundException) {
                // nothing can open it; ignore
            }
            return true
        }

        override fun onPageStarted(view: WebView, url: String?, favicon: Bitmap?) {
            loadingBar.visibility = View.VISIBLE
        }

        override fun onPageFinished(view: WebView, url: String?) {
            loadingBar.visibility = View.GONE
            if (clearHistoryAfterLoad && url != null && url.startsWith(serverUrl())) {
                clearHistoryAfterLoad = false
                view.clearHistory()   // so Back does not return to the error screen
            }
        }

        override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
            if (request.isForMainFrame) showOffline(error.description?.toString() ?: "")
        }

        override fun onReceivedHttpError(view: WebView, request: WebResourceRequest, errorResponse: WebResourceResponse) {
            if (request.isForMainFrame && errorResponse.statusCode >= 400) {
                showOffline("HTTP ${errorResponse.statusCode}: is this the City Memory server, version 1.1 or newer?")
            }
        }
    }

    // ---------------------------------------------------------------- photos

    private inner class Chrome : WebChromeClient() {
        override fun onShowFileChooser(
            view: WebView,
            filePathCallback: ValueCallback<Array<Uri>>,
            fileChooserParams: FileChooserParams
        ): Boolean {
            fileCallback?.onReceiveValue(null)
            fileCallback = filePathCallback

            val gallery = Intent(Intent.ACTION_GET_CONTENT).apply {
                addCategory(Intent.CATEGORY_OPENABLE)
                type = "image/*"
            }
            val extra = ArrayList<Intent>()
            cameraUri = newPhotoUri()
            cameraUri?.let { uri ->
                val camera = Intent(MediaStore.ACTION_IMAGE_CAPTURE).apply {
                    putExtra(MediaStore.EXTRA_OUTPUT, uri)
                    addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION or Intent.FLAG_GRANT_READ_URI_PERMISSION)
                }
                if (camera.resolveActivity(packageManager) != null) extra.add(camera)
            }
            val chooser = Intent.createChooser(gallery, getString(R.string.photo_title))
            chooser.putExtra(Intent.EXTRA_INITIAL_INTENTS, extra.toTypedArray())
            return try {
                startActivityForResult(chooser, REQ_FILE)
                true
            } catch (e: ActivityNotFoundException) {
                fileCallback = null
                false
            }
        }
    }

    /** A place in the phone's Pictures/CityMemory folder for the camera to save into. */
    private fun newPhotoUri(): Uri? = try {
        val values = ContentValues().apply {
            put(MediaStore.Images.Media.DISPLAY_NAME, "citymemory_${System.currentTimeMillis()}.jpg")
            put(MediaStore.Images.Media.MIME_TYPE, "image/jpeg")
            put(MediaStore.Images.Media.RELATIVE_PATH, "Pictures/CityMemory")
        }
        contentResolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values)
    } catch (e: Exception) {
        null
    }

    private fun hasContent(uri: Uri): Boolean = try {
        contentResolver.openInputStream(uri)?.use { it.read() != -1 } ?: false
    } catch (e: Exception) {
        false
    }

    // ---------------------------------------------------------------- voice typing

    private fun launchVoice(languageTag: String) {
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, languageTag)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_PREFERENCE, languageTag)
            putExtra(RecognizerIntent.EXTRA_PROMPT, getString(R.string.voice_prompt))
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
        }
        try {
            startActivityForResult(intent, REQ_VOICE)
        } catch (e: ActivityNotFoundException) {
            js("window.cmOnVoiceError && window.cmOnVoiceError(${quote(getString(R.string.voice_missing))})")
        }
    }

    // ---------------------------------------------------------------- results from camera, gallery, voice

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        when (requestCode) {
            REQ_FILE -> {
                val callback = fileCallback
                fileCallback = null
                val camera = cameraUri
                cameraUri = null
                var result: Array<Uri>? = null
                if (resultCode == RESULT_OK) {
                    val picked = data?.data
                    result = when {
                        picked != null -> arrayOf(picked)
                        camera != null && hasContent(camera) -> arrayOf(camera)
                        else -> null
                    }
                }
                // remove the empty camera file if the camera was not used
                if (camera != null && (result == null || result[0] != camera)) {
                    try {
                        contentResolver.delete(camera, null, null)
                    } catch (e: Exception) {
                        // not important
                    }
                }
                callback?.onReceiveValue(result)
            }
            REQ_VOICE -> {
                val text = if (resultCode == RESULT_OK) {
                    data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull()
                } else null
                js("window.cmOnVoice && window.cmOnVoice(${quote(text ?: "")})")
            }
        }
    }

    // ---------------------------------------------------------------- location

    private fun hasLocationPermission(): Boolean =
        checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED ||
            checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED

    private fun startLocation() {
        if (!hasLocationPermission()) {
            pendingLocation = true
            requestPermissions(
                arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION),
                REQ_LOCATION
            )
            return
        }
        readLocation()
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQ_LOCATION && pendingLocation) {
            pendingLocation = false
            if (grantResults.any { it == PackageManager.PERMISSION_GRANTED }) readLocation()
            else locationError(getString(R.string.loc_denied))
        }
    }

    @SuppressLint("MissingPermission")
    private fun readLocation() {
        if (!hasLocationPermission()) {
            locationError(getString(R.string.loc_denied))
            return
        }
        val lm = getSystemService(LOCATION_SERVICE) as LocationManager
        val providers = listOf(LocationManager.GPS_PROVIDER, LocationManager.NETWORK_PROVIDER).filter {
            try {
                lm.isProviderEnabled(it)
            } catch (e: Exception) {
                false
            }
        }
        if (providers.isEmpty()) {
            locationError(getString(R.string.loc_off))
            return
        }

        // A fix from the last two minutes is good enough, and instant.
        val recent = providers.mapNotNull { lastKnown(lm, it) }
            .filter { System.currentTimeMillis() - it.time < 2 * 60 * 1000 }
            .minByOrNull { it.accuracy }
        if (recent != null) {
            sendLocation(recent)
            return
        }

        var done = false
        val listener = object : LocationListener {
            override fun onLocationChanged(location: Location) {
                if (done) return
                done = true
                lm.removeUpdates(this)
                sendLocation(location)
            }

            override fun onProviderEnabled(provider: String) {}
            override fun onProviderDisabled(provider: String) {}

            @Deprecated("Deprecated in Java")
            override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) {}
        }
        for (p in providers) {
            try {
                lm.requestLocationUpdates(p, 0L, 0f, listener, Looper.getMainLooper())
            } catch (e: Exception) {
                // provider not available on this phone
            }
        }
        main.postDelayed({
            if (!done) {
                done = true
                lm.removeUpdates(listener)
                val older = providers.mapNotNull { lastKnown(lm, it) }.maxByOrNull { it.time }
                if (older != null) sendLocation(older) else locationError(getString(R.string.loc_slow))
            }
        }, 20_000)
    }

    @SuppressLint("MissingPermission")
    private fun lastKnown(lm: LocationManager, provider: String): Location? = try {
        lm.getLastKnownLocation(provider)
    } catch (e: Exception) {
        null
    }

    private fun sendLocation(loc: Location) {
        js("window.cmOnLocation && window.cmOnLocation(${loc.latitude}, ${loc.longitude}, ${loc.accuracy})")
    }

    private fun locationError(message: String) {
        js("window.cmOnLocationError && window.cmOnLocationError(${quote(message)})")
    }
}
