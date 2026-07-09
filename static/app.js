document.addEventListener("DOMContentLoaded", () => {
    const appRoot = document.getElementById("app-root");
    const logoHome = document.getElementById("logo-home");
    
    // Forms & Inputs
    const searchFormHeader = document.getElementById("search-form-header");
    const searchInputHeader = document.getElementById("search-input-header");
    const searchFormHero = document.getElementById("search-form-hero");
    const searchInputHero = document.getElementById("search-input-hero");
    
    const loadingState = document.getElementById("loading");
    const loadingStage = document.getElementById("loading-stage");
    const loadingPercent = document.getElementById("loading-percent");
    const loadingProgressBar = document.getElementById("loading-progress-bar");
    const errorState = document.getElementById("error-state");
    const storiesContainer = document.getElementById("stories-container");
    const resultsMetaTabs = document.getElementById("results-meta-tabs");
    const resultsToolbar = document.getElementById("results-toolbar");
    const resultsSummary = document.getElementById("results-summary");
    const warningsPanel = document.getElementById("warnings-panel");
    const downloadMdBtn = document.getElementById("download-md-btn");
    const downloadJsonBtn = document.getElementById("download-json-btn");
    
    // Columns
    const leftColContainer = document.getElementById("left-col-container");
    const centerColContainer = document.getElementById("center-col-container");
    const rightColContainer = document.getElementById("right-col-container");
    
    const leftColumnCards = document.getElementById("left-column-cards");
    const centerColumnCards = document.getElementById("center-column-cards");
    const rightColumnCards = document.getElementById("right-column-cards");
    
    // Tabs
    const tabLinks = document.querySelectorAll(".tab-link");
    let currentTab = "all";
    
    // Modal Elements
    const modal = document.getElementById("details-modal");
    const modalTitle = document.getElementById("modal-title");
    const modalConfidence = document.getElementById("modal-confidence");
    const modalSourcesCount = document.getElementById("modal-sources-count");
    const modalRecapBody = document.getElementById("modal-recap-body");
    const modalCommonFactsList = document.getElementById("modal-common-facts-list");
    const modalVolatileList = document.getElementById("modal-volatile-list");
    const modalSingleSourceList = document.getElementById("modal-single-source-list");
    const modalUncertainList = document.getElementById("modal-uncertain-list");
    const modalSourceFocusList = document.getElementById("modal-source-focus-list");
    const modalNotesList = document.getElementById("modal-notes-list");
    
    // Modal Bias Chart
    const barLeft = document.getElementById("bar-left");
    const barCenter = document.getElementById("bar-center");
    const barRight = document.getElementById("bar-right");
    const biasSummaryText = document.getElementById("bias-summary-text");
    
    // Modal Lanes
    const laneLeft = document.getElementById("lane-outlets-left");
    const laneCenter = document.getElementById("lane-outlets-center");
    const laneRight = document.getElementById("lane-outlets-right");
    const laneUntracked = document.getElementById("untracked-outlets-list");

    let currentClustersData = [];
    let currentQuery = "";
    let currentWarnings = [];
    let progressTimer = null;
    let progressValue = 0;

    function syncDetailsModalLayout() {
        if (!modal) return;
        const viewport = window.visualViewport || window;
        const viewportWidth = viewport.width || window.innerWidth;
        const viewportHeight = viewport.height || window.innerHeight;
        const widthRatio = viewportWidth < 760 ? 0.98 : 0.96;
        const modalWidth = Math.max(320, Math.min(Math.round(viewportWidth * widthRatio), 1560));
        const modalHeight = Math.max(420, Math.round(viewportHeight * 0.92));

        modal.style.setProperty("--width", `${modalWidth}px`);
        modal.style.setProperty("--details-modal-max-height", `${modalHeight}px`);
        modal.style.setProperty("--details-modal-padding", modalWidth < 760 ? "1.25rem" : (modalWidth < 1180 ? "2rem" : "3rem"));
        modal.classList.toggle("modal-layout-stacked", modalWidth < 1180);
        modal.classList.toggle("trust-lanes-two", modalWidth >= 760 && modalWidth < 1380);
        modal.classList.toggle("trust-lanes-one", modalWidth < 760);
    }

    // ── Settings & Model State ───────────────────────────────────────
    const settingsBtn    = document.getElementById("settings-btn");
    const settingsModal  = document.getElementById("settings-modal");
    const settingsSaveBtn   = document.getElementById("settings-save-btn");
    const settingsCancelBtn = document.getElementById("settings-cancel-btn");
    const settingsApiKey = document.getElementById("settings-api-key");
    const settingsModelName = document.getElementById("settings-model-name");
    const settingsConfigToken = document.getElementById("settings-config-token");
    const settingsStatus = document.getElementById("settings-status");
    const toggleKeyBtn   = document.getElementById("toggle-key-btn");
    const providerGrid   = document.getElementById("provider-grid");
    const apiKeySection  = document.getElementById("api-key-section");
    const modelNameSection = document.getElementById("model-name-section");

    const modelPillBtn   = document.getElementById("model-pill-btn");
    const modelPillLabel = document.getElementById("model-pill-label");
    const modelDropdown  = document.getElementById("model-dropdown");

    let activeProvider = "dry-run";
    let activeModel    = "";
    let keysPresent = {};
    let lastConfigError = "";

    // Model emoji labels for pill
    const PROVIDER_LABELS = {
        "dry-run": "🔬 Dry-Run",
        "openai":  "🤖 OpenAI",
        "gemini":  "💎 Gemini",
        "nim":     "⚡ NVIDIA NIM",
        "local":   "🖥️ Local",
    };

    const PROVIDER_DEFAULT_MODELS = {
        "dry-run": "",
        "openai": "gpt-4o-mini",
        "gemini": "gemini-2.5-flash",
        "nim": "meta/llama-3.1-8b-instruct",
        "local": "gemma4:e4b",
    };

    function modelMatchesProvider(provider, model) {
        if (!model) return true;
        if (provider === "dry-run") return model === "";
        if (provider === "openai") return model.startsWith("gpt-") || model.startsWith("o1-") || model.startsWith("o3-");
        if (provider === "gemini") return model.startsWith("gemini-");
        if (provider === "nim") return model.includes("/") || model.startsWith("nvidia-");
        if (provider === "local") return !model.startsWith("gpt-") && !model.startsWith("gemini-") && !model.includes("/");
        return true;
    }

    function defaultModelForProvider(provider) {
        return PROVIDER_DEFAULT_MODELS[provider] || "";
    }

    function modelForProvider(provider, model) {
        return modelMatchesProvider(provider, model) ? (model || defaultModelForProvider(provider)) : defaultModelForProvider(provider);
    }

    function updateProviderBadge(provider, model) {
        const label = model
            ? `${PROVIDER_LABELS[provider] || provider} · ${model}`
            : (PROVIDER_LABELS[provider] || provider);
        if (modelPillLabel) modelPillLabel.textContent = model || (PROVIDER_LABELS[provider] || provider);
        // Highlight selected in dropdown
        document.querySelectorAll(".model-option").forEach(opt => {
            opt.classList.toggle("selected",
                opt.dataset.provider === provider && opt.dataset.model === model);
        });
    }

    async function readApiResponse(response) {
        const text = await response.text();
        let data = {};
        if (text) {
            try {
                data = JSON.parse(text);
            } catch {
                data = { detail: text };
            }
        }

        if (!response.ok) {
            const detail = data.detail || data.error || response.statusText || "Request failed";
            throw new Error(Array.isArray(detail) ? detail.join(", ") : String(detail));
        }

        return data;
    }

    function parseJsonish(value) {
        if (typeof value !== "string") return value;
        let text = value.trim();
        const fence = text.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i);
        if (fence) text = fence[1].trim();
        if (!text || !["{", "["].includes(text[0])) return value;
        try {
            return JSON.parse(text);
        } catch {
            return value;
        }
    }

    function humanizeValue(value) {
        value = parseJsonish(value);
        if (value === null || value === undefined) return "";
        if (typeof value === "string") return value.trim();
        if (Array.isArray(value)) {
            return value.map(humanizeValue).filter(Boolean).join("; ");
        }
        if (typeof value === "object") {
            const preferredKeys = ["fact", "claim", "summary", "text", "description", "focus", "note", "reason"];
            for (const key of preferredKeys) {
                const preferred = humanizeValue(value[key]);
                if (preferred) {
                    const source = humanizeValue(value.source || value.publisher);
                    return source ? `${source}: ${preferred}` : preferred;
                }
            }
            return Object.entries(value)
                .map(([key, item]) => {
                    const text = humanizeValue(item);
                    return text ? `${key}: ${text}` : "";
                })
                .filter(Boolean)
                .join("; ");
        }
        return String(value).trim();
    }

    function normalizeStringList(value) {
        value = parseJsonish(value);
        if (value === null || value === undefined || value === "") return [];
        if (Array.isArray(value)) {
            return value.map(humanizeValue).filter(Boolean);
        }
        const text = humanizeValue(value);
        return text ? [text] : [];
    }

    function normalizeVolatileElements(value) {
        value = parseJsonish(value);
        if (value === null || value === undefined || value === "") return [];
        const rawItems = Array.isArray(value) ? value : [value];
        return rawItems.map(item => {
            item = parseJsonish(item);
            if (item && typeof item === "object" && !Array.isArray(item)) {
                return {
                    element: humanizeValue(item.element || item.claim || item.detail || "detail"),
                    option_1: humanizeValue(item.option_1 || item.version_1 || item.supported || ""),
                    option_2: humanizeValue(item.option_2 || item.version_2 || item.disputed || ""),
                    reason: humanizeValue(item.reason || item.note || item.explanation || ""),
                };
            }
            return {
                element: "reported detail requiring source comparison",
                option_1: "",
                option_2: humanizeValue(item),
                reason: "The model returned this uncertainty as unstructured text.",
            };
        }).filter(item => item.option_1 || item.option_2 || item.reason);
    }

    function normalizeAnalysis(analysis) {
        analysis = parseJsonish(analysis);
        if (!analysis || typeof analysis !== "object" || Array.isArray(analysis)) analysis = {};
        ["compiled_body", "most_supported_version", "headline"].forEach(key => {
            const nested = parseJsonish(analysis[key]);
            if (nested && typeof nested === "object" && !Array.isArray(nested)) {
                analysis = { ...analysis, ...nested };
            }
        });
        return {
            ...analysis,
            headline: humanizeValue(analysis.headline),
            most_supported_version: humanizeValue(analysis.most_supported_version),
            compiled_body: humanizeValue(analysis.compiled_body),
            paragraph: humanizeValue(analysis.paragraph),
            common_facts: normalizeStringList(analysis.common_facts),
            single_source_claims: normalizeStringList(analysis.single_source_claims),
            uncertain_claims: normalizeStringList(analysis.uncertain_claims),
            source_report_focus: normalizeStringList(analysis.source_report_focus),
            source_notes: normalizeStringList(analysis.source_notes),
            volatile_elements: normalizeVolatileElements(analysis.volatile_elements),
        };
    }

    function withAnalysisFallbacks(cluster, analysis) {
        const articles = cluster.articles || [];
        const sources = uniquePublishers(articles);
        const summary = analysis.compiled_body || analysis.paragraph || analysis.most_supported_version || "";

        if (analysis.common_facts.length === 0) {
            if (analysis.most_supported_version) {
                analysis.common_facts = [analysis.most_supported_version];
            } else if (summary) {
                analysis.common_facts = [firstSentence(summary)];
            } else if (articles.length > 0) {
                analysis.common_facts = [`This cluster groups ${articles.length} article(s) from ${sources.length || cluster.source_count || 0} source(s) around the same reported story.`];
            }
        }

        if (analysis.single_source_claims.length === 0) {
            const sourceCounts = new Map();
            articles.forEach(article => {
                const name = article.publisher || article.source || "Unknown";
                sourceCounts.set(name, (sourceCounts.get(name) || 0) + 1);
            });
            analysis.single_source_claims = articles
                .filter(article => sourceCounts.get(article.publisher || article.source || "Unknown") === 1)
                .slice(0, 3)
                .map(article => `${article.publisher || article.source || "Unknown"}: ${article.title}`);
        }

        if (analysis.uncertain_claims.length === 0) {
            const volatileReasons = (analysis.volatile_elements || [])
                .map(item => item.reason)
                .filter(Boolean);
            if (volatileReasons.length > 0) {
                analysis.uncertain_claims = volatileReasons;
            } else if ((cluster.guardrail_notes || []).length > 0) {
                analysis.uncertain_claims = cluster.guardrail_notes.slice(0, 3);
            }
        }

        if (analysis.source_report_focus.length === 0) {
            analysis.source_report_focus = representativeArticles(articles)
                .slice(0, 6)
                .map(article => `${article.publisher || article.source || "Unknown"}: ${article.title}`);
        }

        if (analysis.source_notes.length === 0) {
            const sourceCount = sources.length || cluster.source_count || 0;
            const articleCount = articles.length || 0;
            if (articleCount > sourceCount && sourceCount > 0) {
                analysis.source_notes.push(`${articleCount} articles come from ${sourceCount} unique source(s), so repeated outlets are not counted as fully independent support.`);
            }
            if ((cluster.guardrail_notes || []).length > 0) {
                analysis.source_notes.push(...cluster.guardrail_notes.slice(0, 2));
            }
        }

        return analysis;
    }

    function representativeArticles(articles) {
        const seen = new Set();
        const reps = [];
        (articles || []).forEach(article => {
            const name = article.publisher || article.source || "Unknown";
            if (!seen.has(name)) {
                seen.add(name);
                reps.push(article);
            }
        });
        return reps;
    }

    function firstSentence(value) {
        const text = humanizeValue(value);
        const match = text.match(/^(.+?[.!?])\s/);
        return match ? match[1] : text;
    }

    function normalizeCluster(cluster) {
        const analysis = normalizeAnalysis(cluster.analysis || {});
        return {
            ...cluster,
            analysis: withAnalysisFallbacks(cluster, analysis),
        };
    }

    // ── Model Dropdown ───────────────────────────────────────────────
    modelPillBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        modelDropdown.classList.toggle("open");
    });

    document.addEventListener("click", () => modelDropdown.classList.remove("open"));

    document.querySelectorAll(".model-option").forEach(opt => {
        opt.addEventListener("click", async () => {
            const provider = opt.dataset.provider;
            const model    = opt.dataset.model;
            modelDropdown.classList.remove("open");

            if (provider === "dry-run" || provider === "local" || keysPresent[provider]) {
                const ok = await applyConfig(provider, "", model);
                if (ok && provider === "local") {
                    await checkLocalLLMStatus({ silent: false });
                }
            } else {
                // Open settings modal pre-filled
                selectProvider(provider);
                settingsModelName.value = model || "";
                settingsModal.show();
            }
        });
    });

    // ── Settings Modal ───────────────────────────────────────────────
    settingsBtn.addEventListener("click", () => settingsModal.show());
    settingsCancelBtn.addEventListener("click", () => settingsModal.hide());

    // Toggle API key visibility
    toggleKeyBtn.addEventListener("click", () => {
        const isHidden = settingsApiKey.type === "password";
        settingsApiKey.type = isHidden ? "text" : "password";
        toggleKeyBtn.querySelector("i").className = isHidden ? "fa-solid fa-eye-slash" : "fa-solid fa-eye";
    });

    // Provider card selection inside modal
    function selectProvider(provider, { keepModel = false } = {}) {
        document.querySelectorAll(".provider-card").forEach(card => {
            card.classList.toggle("active", card.dataset.provider === provider);
        });
        // Show/hide key field
        const needsKey = provider === "openai" || provider === "gemini" || provider === "nim";
        apiKeySection.style.display    = needsKey ? "" : "none";
        modelNameSection.style.display = provider !== "dry-run" ? "" : "none";
        if (needsKey) {
            settingsApiKey.placeholder = keysPresent[provider] ? "Key already loaded from .env" : "sk-... or AIza... or nvapi-...";
        }
        if (!keepModel) {
            settingsModelName.value = modelForProvider(provider, settingsModelName.value.trim());
        } else if (settingsModelName.value.trim() && !modelMatchesProvider(provider, settingsModelName.value.trim())) {
            settingsModelName.value = defaultModelForProvider(provider);
        }
        if (provider === "local") {
            checkLocalLLMStatus({ silent: true });
        }
    }

    providerGrid.querySelectorAll(".provider-card").forEach(card => {
        card.addEventListener("click", () => selectProvider(card.dataset.provider));
    });

    // Save button
    settingsSaveBtn.addEventListener("click", async () => {
        const providerCards = providerGrid.querySelectorAll(".provider-card.active");
        const provider = providerCards.length ? providerCards[0].dataset.provider : "dry-run";
        const apiKey   = settingsApiKey.value.trim();
        const model    = modelForProvider(provider, settingsModelName.value.trim());
        const configToken = settingsConfigToken ? settingsConfigToken.value.trim() : "";
        const activeCard = providerCards[0];
        const hasEnvKey  = activeCard && activeCard.querySelector(".key-badge");

        if ((provider === "openai" || provider === "gemini" || provider === "nim") && !apiKey && !hasEnvKey) {
            showStatus("error", "Please enter an API key for this provider.");
            return;
        }

        settingsSaveBtn.setAttribute("loading", "");
        if (configToken) {
            window.localStorage.setItem("CONFIG_WRITE_TOKEN", configToken);
        } else {
            window.localStorage.removeItem("CONFIG_WRITE_TOKEN");
        }
        const ok = await applyConfig(provider, apiKey, model);
        settingsSaveBtn.removeAttribute("loading");

        if (ok) {
            showStatus("success", "✓ Settings saved! AI provider is now active.");
            if (provider === "local") {
                await checkLocalLLMStatus({ silent: false });
            }
            setTimeout(() => settingsModal.hide(), 1200);
        } else {
            showStatus("error", lastConfigError || "Failed to save settings. Check the server.");
        }
    });

    function showStatus(type, msg) {
        settingsStatus.textContent = msg;
        settingsStatus.className = `settings-status ${type}`;
        settingsStatus.classList.remove("hidden");
    }

    async function applyConfig(provider, apiKey, model) {
        try {
            lastConfigError = "";
            const headers = { "Content-Type": "application/json" };
            const configToken = window.localStorage.getItem("CONFIG_WRITE_TOKEN") || "";
            if (configToken) headers["X-Config-Token"] = configToken;

            const res = await fetch("/api/config", {
                method: "POST",
                headers,
                body: JSON.stringify({ provider, api_key: apiKey, model })
            });
            const data = await readApiResponse(res);
            activeProvider = data.provider || provider;
            activeModel    = data.model || model || "";
            keysPresent = data.keys_present || keysPresent;
            updateProviderBadge(activeProvider, activeModel);
            markProviderKeys(keysPresent);
            return true;
        } catch (error) {
            lastConfigError = error.message || "Failed to save settings. Check the server.";
            return false;
        }
    }

    async function checkLocalLLMStatus({ silent = false } = {}) {
        try {
            const res = await fetch("/api/local-llm/status");
            const data = await readApiResponse(res);
            if (!silent || activeProvider === "local") {
                const type = data.connected ? "success" : "error";
                const label = data.connected ? "Local Ollama connected" : "Local Ollama not reachable";
                showStatus(type, `${label}: ${data.base_url} · ${data.model}`);
            }
            return data.connected;
        } catch (error) {
            if (!silent) {
                showStatus("error", error.message || "Could not check Local Ollama status.");
            }
            return false;
        }
    }

    function markProviderKeys(keys) {
        document.querySelectorAll(".provider-card").forEach(card => {
            const p = card.dataset.provider;
            const existing = card.querySelector(".key-badge");
            if (keys[p]) {
                if (!existing) {
                    const b = document.createElement("span");
                    b.className = "key-badge";
                    b.textContent = p === "local" ? "local" : "key";
                    card.appendChild(b);
                }
            } else if (existing) {
                existing.remove();
            }
        });
    }

    // Load current config on startup
    async function initConfig() {
        try {
            const res = await fetch("/api/config");
            const cfg = await res.json();
            activeProvider = cfg.provider || "dry-run";
            activeModel    = modelForProvider(activeProvider, cfg.model || "");
            updateProviderBadge(activeProvider, activeModel);
            // Pre-select correct provider card in modal
            settingsModelName.value = activeModel;
            selectProvider(activeProvider, { keepModel: true });
            if (settingsConfigToken) {
                settingsConfigToken.value = window.localStorage.getItem("CONFIG_WRITE_TOKEN") || "";
            }

            // Mark provider cards that have keys already in .env with a ✓
            keysPresent = cfg.keys_present || {};
            markProviderKeys(keysPresent);
        } catch {}
    }
    initConfig();
    if (settingsConfigToken) {
        settingsConfigToken.value = window.localStorage.getItem("CONFIG_WRITE_TOKEN") || "";
    }

    // --- Search Submission ---
    searchFormHeader.addEventListener("submit", (e) => {
        e.preventDefault();
        const query = searchInputHeader.value.trim();
        if (!query) return;
        performSearch(query);
    });

    searchFormHero.addEventListener("submit", (e) => {
        e.preventDefault();
        const query = searchInputHero.value.trim();
        if (!query) return;
        performSearch(query);
    });

    // Logo Click -> Reset to initial home state and reload trending keywords
    logoHome.addEventListener("click", () => {
        appRoot.className = "app-container initial-state";
        searchInputHero.value = "";
        searchInputHeader.value = "";
        storiesContainer.classList.add("hidden");
        resultsMetaTabs.classList.add("hidden");
        resultsToolbar.classList.add("hidden");
        errorState.classList.add("hidden");
        modal.hide();
        loadTrendingKeywords();
    });

    function updateLoadingProgress(value, label) {
        progressValue = Math.max(0, Math.min(100, value));
        const rounded = Math.round(progressValue);
        if (loadingProgressBar) loadingProgressBar.style.width = `${rounded}%`;
        if (loadingPercent) loadingPercent.textContent = `${rounded}%`;
        if (loadingStage && label) loadingStage.textContent = label;
    }

    function stageForProgress(value) {
        if (value < 12) return "Preparing query variants and source settings...";
        if (value < 24) return "Collecting candidates from Google News RSS, Brave, GDELT, and NewsAPI...";
        if (value < 36) return "Deduplicating article URLs and preserving metadata/images...";
        if (value < 50) return "Fetching article pages and recovering snippets when pages are blocked...";
        if (value < 62) return "Extracting article text, dates, publishers, and images...";
        if (value < 72) return "Clustering related articles into story groups...";
        if (value < 82) return "Scoring source trust and independent-source support...";
        if (value < 92) return "Running the selected AI model for synthesis and conflict checks...";
        if (value < 97) return "Large search still running. Waiting for final server response...";
        return "Finalizing verification report...";
    }

    function startLoadingProgress() {
        clearInterval(progressTimer);
        updateLoadingProgress(3, "Starting search...");
        progressTimer = setInterval(() => {
            const increment = progressValue < 35 ? 4 : progressValue < 70 ? 2 : progressValue < 92 ? 0.75 : 0.2;
            const next = progressValue + increment;
            updateLoadingProgress(Math.min(next, 98), stageForProgress(next));
        }, 650);
    }

    function finishLoadingProgress() {
        clearInterval(progressTimer);
        updateLoadingProgress(100, "Done. Rendering results...");
    }

    function stopLoadingProgress() {
        clearInterval(progressTimer);
        progressTimer = null;
    }

    async function performSearch(query) {
        // Synchronize inputs
        searchInputHero.value = query;
        searchInputHeader.value = query;
        currentQuery = query;
        currentWarnings = [];

        // Transition states
        appRoot.classList.remove("initial-state");
        appRoot.classList.add("results-state");

        // Show Loading, Hide contents
        loadingState.classList.remove("hidden");
        errorState.classList.add("hidden");
        storiesContainer.classList.add("hidden");
        resultsMetaTabs.classList.add("hidden");
        resultsToolbar.classList.add("hidden");
        
        leftColumnCards.innerHTML = "";
        centerColumnCards.innerHTML = "";
        rightColumnCards.innerHTML = "";
        renderWarnings([]);
        startLoadingProgress();
        
        try {
            const response = await fetch(`/api/search?q=${encodeURIComponent(query)}&limit=12&variants=5&max_articles=60&analysis_limit=3&fetch_timeout=12`);
            const data = await readApiResponse(response);
            finishLoadingProgress();
            
            // Keep the visible model pill in sync with the backend response.
            if (data.provider) {
                activeProvider = data.provider;
                activeModel = data.model || "";
                updateProviderBadge(activeProvider, activeModel);
            }
            
            currentClustersData = (data.clusters || []).map(normalizeCluster);
            currentWarnings = data.warnings || [];
            
            if (currentClustersData.length === 0) {
                renderResultsSummary(currentClustersData, currentWarnings);
                renderWarnings(currentWarnings);
                showEmptyState("No matching stories found.", "Try searching for another topic or simplify your keywords.");
                if (currentWarnings.length > 0) {
                    resultsToolbar.classList.remove("hidden");
                }
            } else {
                renderClusters(currentClustersData);
                renderResultsSummary(currentClustersData, currentWarnings);
                renderWarnings(currentWarnings);
                applyTabFilter(currentTab);
                loadingState.classList.add("hidden");
                storiesContainer.classList.remove("hidden");
                resultsMetaTabs.classList.remove("hidden");
                resultsToolbar.classList.remove("hidden");
            }
        } catch (error) {
            console.error("Search failed:", error);
            showEmptyState("An error occurred during search.", error.message || "Please check the server connection and configurations, then try again.");
        } finally {
            stopLoadingProgress();
        }
    }

    function showEmptyState(title, subtitle) {
        loadingState.classList.add("hidden");
        storiesContainer.classList.add("hidden");
        resultsMetaTabs.classList.add("hidden");
        resultsToolbar.classList.add("hidden");
        errorState.classList.remove("hidden");
        
        errorState.querySelector("h2").textContent = title;
        errorState.querySelector("p").textContent = subtitle;
    }

    function renderWarnings(warnings) {
        if (!warningsPanel) return;
        // Filter out low-level fetch extractor errors — users don't need to see these
        const cleanWarnings = (warnings || [])
            .filter(Boolean)
            .filter(w => !w.startsWith("Failed to fetch") && !w.includes("All extractors failed"));
        if (cleanWarnings.length === 0) {
            warningsPanel.classList.add("hidden");
            warningsPanel.innerHTML = "";
            return;
        }
        const visible = cleanWarnings.slice(0, 3);
        warningsPanel.classList.remove("hidden");
        warningsPanel.innerHTML = `
            <div class="warnings-title"><i class="fa-solid fa-circle-info"></i> Partial fetch warnings</div>
            <ul>
                ${visible.map(warning => `<li>${escapeHTML(warning)}</li>`).join("")}
            </ul>
            ${cleanWarnings.length > visible.length ? `<div class="warnings-more">+${cleanWarnings.length - visible.length} more warning(s)</div>` : ""}
        `;
    }

    function renderResultsSummary(clusters, warnings) {
        if (!resultsSummary) return;
        const articleCount = (clusters || []).reduce((total, cluster) => total + (cluster.articles || []).length, 0);
        const sourceNames = new Set();
        (clusters || []).forEach(cluster => {
            (cluster.articles || []).forEach(article => sourceNames.add(article.publisher || article.source || "Unknown"));
        });
        resultsSummary.innerHTML = `
            <span class="summary-pill" title="Story clusters are groups of articles that appear to cover the same event."><strong>${clusters.length}</strong> story cluster${clusters.length === 1 ? "" : "s"} <i class="fa-regular fa-circle-question"></i></span>
            <span class="summary-pill" title="Articles are fetched URLs kept after discovery, deduplication, and scraping or snippet fallback."><strong>${articleCount}</strong> article${articleCount === 1 ? "" : "s"} <i class="fa-regular fa-circle-question"></i></span>
            <span class="summary-pill" title="Sources are unique publishers or domains represented across the fetched articles. Multiple articles can come from one source."><strong>${sourceNames.size}</strong> source${sourceNames.size === 1 ? "" : "s"} <i class="fa-regular fa-circle-question"></i></span>
            <span class="summary-pill" title="Warnings are non-fatal fetch or API issues. The system continues with available sources when possible."><strong>${(warnings || []).length}</strong> warning${(warnings || []).length === 1 ? "" : "s"} <i class="fa-regular fa-circle-question"></i></span>
        `;
    }

    function downloadFile(filename, content, type) {
        const blob = new Blob([content], { type });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
    }

    function slugify(value) {
        return (value || "storycompare-report")
            .toLowerCase()
            .replace(/[^a-z0-9가-힣]+/gi, "-")
            .replace(/^-+|-+$/g, "")
            .slice(0, 60) || "storycompare-report";
    }

    function reportMarkdown() {
        const lines = [`# StoryCompare Report`, "", `Query: ${currentQuery || "Untitled"}`, ""];
        if (currentWarnings.length) {
            lines.push("## Partial Fetch Warnings", "");
            currentWarnings.forEach(warning => lines.push(`- ${warning}`));
            lines.push("");
        }
        currentClustersData.forEach(cluster => {
            const analysis = cluster.analysis || {};
            lines.push(`## Story #${cluster.cluster_id}: ${analysis.headline || cluster.articles?.[0]?.title || "Untitled story"}`, "");
            lines.push(`- Sources: ${cluster.source_count}`);
            lines.push(`- Trust status: ${cluster.trust_status}`);
            lines.push(`- Confidence: ${cluster.confidence?.confidence || cluster.confidence?.label || "Unknown"}`);
            lines.push("");

            appendMarkdownList(lines, "Common Facts", analysis.common_facts);
            appendMarkdownList(lines, "Conflict / Uncertain Details", (analysis.volatile_elements || []).map(item => {
                if (typeof item !== "object") return String(item);
                return `${item.element || "Detail"}: ${item.option_1 || ""} | ${item.option_2 || ""}${item.reason ? ` (${item.reason})` : ""}`;
            }));
            appendMarkdownList(lines, "Single Source Information", analysis.single_source_claims);
            appendMarkdownList(lines, "Uncertain Information", analysis.uncertain_claims);
            appendMarkdownList(lines, "What Each Source Emphasized", analysis.source_report_focus);
            appendMarkdownList(lines, "Source Quality Notes", analysis.source_notes);
            lines.push("### AI Neutral Recap", "", analysis.compiled_body || analysis.paragraph || "No summary generated.", "");
        });
        return lines.join("\n");
    }

    function appendMarkdownList(lines, title, items) {
        const list = (items || []).filter(Boolean);
        if (!list.length) return;
        lines.push(`### ${title}`, "");
        list.forEach(item => lines.push(`- ${item}`));
        lines.push("");
    }

    downloadMdBtn.addEventListener("click", () => {
        downloadFile(`${slugify(currentQuery)}.md`, reportMarkdown(), "text/markdown;charset=utf-8");
    });

    downloadJsonBtn.addEventListener("click", () => {
        const payload = {
            query: currentQuery,
            warnings: currentWarnings,
            clusters: currentClustersData,
        };
        downloadFile(`${slugify(currentQuery)}.json`, JSON.stringify(payload, null, 2), "application/json;charset=utf-8");
    });

    // --- Tab Filtering ---
    tabLinks.forEach(tab => {
        tab.addEventListener("click", () => {
            tabLinks.forEach(t => t.classList.remove("active"));
            tab.classList.add("active");
            currentTab = tab.getAttribute("data-tab");
            
            applyTabFilter(currentTab);
        });
    });

    function applyTabFilter(tab) {
        if (!storiesContainer.classList.contains("hidden")) {
            if (tab === "all") {
                leftColContainer.classList.remove("hidden");
                centerColContainer.classList.remove("hidden");
                rightColContainer.classList.remove("hidden");
            } else if (tab === "high-trust") {
                leftColContainer.classList.remove("hidden");
                centerColContainer.classList.add("hidden");
                rightColContainer.classList.add("hidden");
            } else if (tab === "low-trust") {
                leftColContainer.classList.add("hidden");
                centerColContainer.classList.add("hidden");
                rightColContainer.classList.remove("hidden");
            }
        }
    }

    // --- Render Story Cards ---
    function renderClusters(clusters) {
        clusters.forEach(cluster => {
            const card = createStoryCard(cluster);
            
            // Categorize cards based on trust status
            const status = cluster.trust_status;
            if (status === "Highly Verified") {
                leftColumnCards.appendChild(card);
            } else if (status === "Unverified / Speculative") {
                rightColumnCards.appendChild(card);
            } else {
                centerColumnCards.appendChild(card);
            }
        });

        // If a column is empty, show a small placeholder message
        if (leftColumnCards.children.length === 0) {
            leftColumnCards.innerHTML = '<div class="empty-column-msg">No highly verified stories detected.</div>';
        }
        if (rightColumnCards.children.length === 0) {
            rightColumnCards.innerHTML = '<div class="empty-column-msg">No speculative stories detected.</div>';
        }
        if (centerColumnCards.children.length === 0) {
            centerColumnCards.innerHTML = '<div class="empty-column-msg">No mixed reliability stories available.</div>';
        }
    }

    function createStoryCard(cluster) {
        // Find the first article with a real image URL (not favicon/icon sized ones)
        const validArticle = cluster.articles.find(a => a.image_url && !a.image_url.includes("favicon")) || cluster.articles[0];
        const imageUrl = validArticle ? validArticle.image_url : "";
        const displayImageUrl = proxiedImageUrl(imageUrl);
        const headline = cluster.analysis.headline || cluster.articles[0].title;
        const sourceCount = cluster.source_count;
        const dist = cluster.trust_distribution;
        const status = cluster.trust_status;
        const volatile = cluster.analysis.volatile_elements || [];
        const conflictCount = volatile.length;
        const publishers = uniquePublishers(cluster.articles).slice(0, 3);
        const dateLabel = dateRangeLabel(cluster.articles);
        const factStatus = clusterFactStatus(cluster);
        const conflictBadgeHTML = conflictCount > 0
            ? `<div class="conflict-strip"><i class="fa-solid fa-triangle-exclamation"></i> ${conflictCount} conflict detail${conflictCount > 1 ? "s" : ""} detected</div>`
            : "";
        
        // Trust status badge
        let bsBadgeHTML = '';
        if (status === "Highly Verified") {
            bsBadgeHTML = `<span class="badge-blindspot balanced"><i class="fa-solid fa-square-check"></i> Verified</span>`;
        } else if (status === "Partially Verified" || status === "Mixed Reliability") {
            bsBadgeHTML = `<span class="badge-blindspot left-bs"><i class="fa-solid fa-triangle-exclamation"></i> Mixed</span>`;
        } else {
            bsBadgeHTML = `<span class="badge-blindspot right-bs"><i class="fa-solid fa-circle-question"></i> Speculative</span>`;
        }

        const imgHTML = displayImageUrl
            ? `<img class="story-card-img" src="${escapeHTML(displayImageUrl)}" alt="" loading="lazy" onerror="this.style.display='none'; this.parentElement.querySelector('.story-img-fallback').style.display='flex';">`
            : "";
        const fallbackHTML = `<div class="story-img-fallback" style="display:${displayImageUrl ? 'none' : 'flex'}"><i class="fa-regular fa-image"></i></div>`;

        const div = document.createElement("div");
        div.className = "story-card";
        div.innerHTML = `
            <div class="story-image-placeholder">
                ${imgHTML}
                ${fallbackHTML}
                <div class="card-badges">
                    ${bsBadgeHTML}
                    <span class="card-sources-count">${sourceCount} sources</span>
                </div>
            </div>
            <div class="story-card-content">
                <h4 class="story-headline">${escapeHTML(headline)}</h4>
                <div class="story-card-meta">
                    <span><i class="fa-regular fa-newspaper"></i> ${escapeHTML(publishers.join(", ") || "Unknown source")}</span>
                    <span><i class="fa-regular fa-calendar"></i> ${escapeHTML(dateLabel)}</span>
                </div>
                <div class="fact-status-pill ${factStatus.className}">
                    <i class="${factStatus.icon}"></i> ${escapeHTML(factStatus.label)}
                </div>
                ${conflictBadgeHTML}
                <div class="mini-bias-metrics">
                    <div class="mini-bias-row">
                        <span>High ${dist.high}%</span>
                        <span>Med ${dist.medium}%</span>
                        <span>Low ${dist.low}%</span>
                    </div>
                    <div class="mini-bias-bar-wrapper">
                        <div class="mini-segment l" style="width: ${dist.high}%"></div>
                        <div class="mini-segment c" style="width: ${dist.medium}%"></div>
                        <div class="mini-segment r" style="width: ${dist.low}%"></div>
                    </div>
                </div>
            </div>
        `;

        div.addEventListener("click", () => {
            openDetailsModal(cluster);
        });

        return div;
    }

    function uniquePublishers(articles) {
        const seen = new Set();
        const names = [];
        (articles || []).forEach(article => {
            const name = article.publisher || article.source || "Unknown";
            if (!seen.has(name)) {
                seen.add(name);
                names.push(name);
            }
        });
        return names;
    }

    function dateRangeLabel(articles) {
        const dates = (articles || [])
            .map(article => article.date)
            .filter(Boolean)
            .sort();
        if (dates.length === 0) return "Date not confirmed";
        const first = dates[0];
        const last = dates[dates.length - 1];
        return first === last ? first : `${first} to ${last}`;
    }

    function clusterFactStatus(cluster) {
        const analysis = cluster.analysis || {};
        const commonCount = (analysis.common_facts || []).length;
        const conflictCount = (analysis.volatile_elements || []).length;
        const singleCount = (analysis.single_source_claims || []).length;
        if (conflictCount > 0) {
            return { label: `${conflictCount} conflict item${conflictCount > 1 ? "s" : ""}`, className: "conflict", icon: "fa-solid fa-triangle-exclamation" };
        }
        if (commonCount > 0) {
            return { label: `${commonCount} common fact${commonCount > 1 ? "s" : ""}`, className: "verified", icon: "fa-solid fa-list-check" };
        }
        if (singleCount > 0) {
            return { label: `${singleCount} single-source claim${singleCount > 1 ? "s" : ""}`, className: "single", icon: "fa-solid fa-link" };
        }
        return { label: "Needs more corroboration", className: "uncertain", icon: "fa-solid fa-circle-question" };
    }

    // --- Modal Actions ---
    function openDetailsModal(cluster) {
        const headline = cluster.analysis.headline || cluster.articles[0].title;
        const recapBody = cluster.analysis.compiled_body || cluster.analysis.paragraph || "No summary was generated.";
        const confidenceVal = cluster.confidence?.confidence || "Medium";
        
        modalTitle.textContent = headline;
        modalConfidence.textContent = `Confidence: ${confidenceVal}`;
        modalConfidence.style.backgroundColor = 
            confidenceVal === "High" ? "rgba(16, 185, 129, 0.15)" : 
            (confidenceVal === "Medium" ? "rgba(245, 158, 11, 0.15)" : "rgba(239, 68, 68, 0.15)");
        modalConfidence.style.color = 
            confidenceVal === "High" ? "#10b981" : 
            (confidenceVal === "Medium" ? "#f59e0b" : "#ef4444");

        modalSourcesCount.textContent = `${cluster.source_count} sources`;
        modalRecapBody.textContent = recapBody;
        renderAnalysisList(
            modalCommonFactsList,
            cluster.analysis.common_facts,
            "No separate common-fact bullets were extracted; use the recap and source emphasis below as the working summary."
        );
        renderAnalysisList(
            modalSingleSourceList,
            cluster.analysis.single_source_claims,
            "No single-source-only claims were separated from the current article cluster."
        );
        renderAnalysisList(
            modalUncertainList,
            cluster.analysis.uncertain_claims,
            "No additional uncertainty was separated beyond the conflict checks and guardrails."
        );
        renderAnalysisList(
            modalSourceFocusList,
            cluster.analysis.source_report_focus,
            "No per-source emphasis was separated; review the recap and article list."
        );

        // Render Banner Image in Modal
        const validArticle = cluster.articles.find(a => a.image_url && !a.image_url.includes("favicon")) || cluster.articles[0];
        const imageUrl = validArticle ? validArticle.image_url : "";
        const displayImageUrl = proxiedImageUrl(imageUrl);
        const modalBanner = document.getElementById("modal-banner");
        if (displayImageUrl) {
            modalBanner.innerHTML = `<img class="modal-banner-img" src="${escapeHTML(displayImageUrl)}" alt="" onerror="this.parentElement.classList.add('hidden')">`;
            modalBanner.style.backgroundImage = "";
            modalBanner.classList.remove("hidden");
        } else {
            modalBanner.classList.add("hidden");
        }

        // Volatile conflicts
        modalVolatileList.innerHTML = "";
        const volatile = cluster.analysis.volatile_elements || [];
        if (volatile.length === 0) {
            modalVolatileList.innerHTML = "<li>No separate conflicting detail was detected in this article cluster.</li>";
        } else {
            volatile.forEach(item => {
                if (typeof item === 'object') {
                    const li = document.createElement("li");
                    let content = `<strong>${escapeHTML(item.element || 'Detail')}:</strong> `;
                    if (item.option_1) content += `${escapeHTML(item.option_1)}`;
                    if (item.option_2) content += ` | ${escapeHTML(item.option_2)}`;
                    if (item.reason) content += ` <br><span class="text-muted" style="font-size: 0.8rem;">Reason: ${escapeHTML(item.reason)}</span>`;
                    li.innerHTML = content;
                    modalVolatileList.appendChild(li);
                } else {
                    const li = document.createElement("li");
                    li.textContent = String(item);
                    modalVolatileList.appendChild(li);
                }
            });
        }

        // Notes
        modalNotesList.innerHTML = "";
        const focusSet = new Set((cluster.analysis.source_report_focus || []).map(item => String(item).trim().toLowerCase()));
        const notes = (cluster.analysis.source_notes || [])
            .filter(note => !focusSet.has(String(note).trim().toLowerCase()));
        if (notes.length === 0) {
            modalNotesList.innerHTML = "<li>No separate source-quality notes were generated beyond the per-source focus above.</li>";
        } else {
            notes.forEach(note => {
                const li = document.createElement("li");
                li.textContent = note;
                modalNotesList.appendChild(li);
            });
        }

        // --- Render Trust Distribution graphic ---
        const dist = cluster.trust_distribution;
        barLeft.style.width = `${dist.high}%`;
        barLeft.textContent = dist.high > 8 ? `HIGH ${dist.high}%` : "";
        barCenter.style.width = `${dist.medium}%`;
        barCenter.textContent = dist.medium > 8 ? `MED ${dist.medium}%` : "";
        barRight.style.width = `${dist.low}%`;
        barRight.textContent = dist.low > 8 ? `LOW ${dist.low}%` : "";

        // Header summary text
        const maxTrust = Math.max(dist.high, dist.medium, dist.low);
        let summaryText = "";
        if (maxTrust === dist.high) {
            summaryText = `${dist.high}% of the sources are High Trust`;
        } else if (maxTrust === dist.medium) {
            summaryText = `${dist.medium}% of the sources are Medium Trust`;
        } else {
            summaryText = `${dist.low}% of the sources are Low / Speculative Trust`;
        }
        biasSummaryText.textContent = summaryText;

        // Reset lanes
        laneLeft.innerHTML = "";
        laneCenter.innerHTML = "";
        laneRight.innerHTML = "";
        laneUntracked.innerHTML = "";

        // Sort unique publishers into lanes
        const seenPublishers = new Set();
        cluster.articles.forEach(article => {
            const pub = article.publisher || "Unknown";
            const key = `${pub}_${article.bias}`;
            if (seenPublishers.has(key)) return;
            seenPublishers.add(key);

            const chip = createOutletChip(pub, article.trust, article.url);
            
            if (article.bias === "untracked") {
                const uChip = createUntrackedChip(pub, article.url);
                laneUntracked.appendChild(uChip);
            } else if (article.trust >= 0.85) {
                laneLeft.appendChild(chip);
            } else if (article.trust >= 0.70) {
                laneCenter.appendChild(chip);
            } else {
                laneRight.appendChild(chip);
            }
        });

        // Show placeholders if empty
        if (laneLeft.children.length === 0) laneLeft.innerHTML = '<span class="text-muted" style="font-size:0.75rem;">None</span>';
        if (laneCenter.children.length === 0) laneCenter.innerHTML = '<span class="text-muted" style="font-size:0.75rem;">None</span>';
        if (laneRight.children.length === 0) laneRight.innerHTML = '<span class="text-muted" style="font-size:0.75rem;">None</span>';
        if (laneUntracked.children.length === 0) laneUntracked.innerHTML = '<span class="text-muted" style="font-size:0.75rem; margin-top:0.5rem;">None detected</span>';

        syncDetailsModalLayout();
        modal.show();
        requestAnimationFrame(syncDetailsModalLayout);
    }

    function renderAnalysisList(target, items, emptyText) {
        if (!target) return;
        target.innerHTML = "";
        const cleanItems = (items || []).filter(Boolean);
        if (cleanItems.length === 0) {
            const li = document.createElement("li");
            li.textContent = emptyText;
            li.className = "muted-list-item";
            target.appendChild(li);
            return;
        }
        cleanItems.forEach(item => {
            const li = document.createElement("li");
            li.textContent = String(item);
            target.appendChild(li);
        });
    }

    function createOutletChip(name, bias, url) {
        const a = document.createElement("a");
        a.className = "outlet-chip";
        a.href = url || "#";
        a.target = "_blank";
        
        const firstLetter = name.charAt(0);
        a.innerHTML = `
            <div class="outlet-logo-placeholder">${escapeHTML(firstLetter)}</div>
            <span class="outlet-name" title="${escapeHTML(name)}">${escapeHTML(name)}</span>
        `;
        return a;
    }

    function createUntrackedChip(name, url) {
        const a = document.createElement("a");
        a.className = "untracked-chip";
        a.href = url || "#";
        a.target = "_blank";
        
        const firstLetter = name.charAt(0);
        a.innerHTML = `
            <div class="untracked-logo-placeholder">${escapeHTML(firstLetter)}</div>
            <span class="outlet-name" title="${escapeHTML(name)}">${escapeHTML(name)}</span>
        `;
        return a;
    }

    function escapeHTML(str) {
        if (!str) return "";
        return str
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function proxiedImageUrl(url) {
        if (!url) return "";
        return `/api/image-proxy?url=${encodeURIComponent(url)}`;
    }

    // Dynamic Datetime update
    function updateTimestamp() {
        const badge = document.getElementById("trending-timestamp");
        if (!badge) return;
        const now = new Date();
        const yyyy = now.getFullYear();
        const mm = String(now.getMonth() + 1).padStart(2, "0");
        const dd = String(now.getDate()).padStart(2, "0");
        const hh = String(now.getHours()).padStart(2, "0");
        const min = String(now.getMinutes()).padStart(2, "0");
        const ss = String(now.getSeconds()).padStart(2, "0");
        badge.textContent = `${yyyy}-${mm}-${dd} ${hh}:${min}:${ss}`;
    }

    setInterval(updateTimestamp, 1000);
    updateTimestamp();

    let keywordRotationInterval = null;

    async function loadTrendingKeywords() {
        const chipsContainer = document.getElementById("hero-quick-chips");
        if (!chipsContainer) return;
        
        chipsContainer.innerHTML = '<span class="text-muted" style="font-size:0.8rem;">Loading keywords...</span>';
        if (keywordRotationInterval) {
            clearInterval(keywordRotationInterval);
        }
        
        try {
            const response = await fetch("/api/trending-keywords?num=10");
            const data = await response.json();
            const keywords = data.keywords || [];
            updateTrendingStatus(data);
            
            chipsContainer.innerHTML = "";
            if (keywords.length === 0) {
                chipsContainer.innerHTML = '<span class="text-muted" style="font-size:0.8rem;">No keywords available.</span>';
                return;
            }
            
            let showFirstPage = true;
            
            function renderKeywordPage() {
                // 1. Flip out existing chips
                const currentChips = chipsContainer.querySelectorAll(".chip-btn");
                if (currentChips.length > 0) {
                    currentChips.forEach(chip => {
                        chip.classList.add("flip-out");
                    });
                }
                
                // 2. Wait for flip-out to finish, then draw new ones
                setTimeout(() => {
                    chipsContainer.innerHTML = "";
                    const startIndex = showFirstPage ? 0 : 5;
                    const pageKeywords = keywords.slice(startIndex, startIndex + 5);
                    
                    pageKeywords.forEach((keyword, index) => {
                        const globalRank = startIndex + index + 1;
                        const btn = document.createElement("button");
                        btn.className = "chip-btn flip-out"; // start flipped
                        btn.setAttribute("data-query", keyword);
                        
                        // Color scale for ranks
                        let rankColor = "#10b981"; // #1
                        if (globalRank === 2) rankColor = "#f59e0b";
                        if (globalRank === 3) rankColor = "#3b82f6";
                        if (globalRank > 3) rankColor = "var(--text-muted)";
                        
                        btn.innerHTML = `
                            <span class="rank-num" style="color: ${rankColor}; font-weight:800; font-family:monospace;">#${globalRank}</span>
                            <span>${escapeHTML(keyword)}</span>
                        `;
                        
                        btn.addEventListener("click", () => {
                            searchInputHero.value = keyword;
                            searchInputHeader.value = keyword;
                            searchInputHero.focus();
                        });
                        
                        chipsContainer.appendChild(btn);
                        
                        // Cascade flip-in
                        setTimeout(() => {
                            btn.classList.remove("flip-out");
                        }, 50 + (index * 50));
                    });
                    
                    showFirstPage = !showFirstPage;

                    // Auto-shrink: if chips overflow the container, reduce font-size until they fit
                    requestAnimationFrame(() => {
                        const chips = chipsContainer.querySelectorAll(".chip-btn");
                        let fontSize = 0.82; // rem — starting size
                        const minFontSize = 0.62; // rem — floor

                        function checkOverflow() {
                            if (chipsContainer.scrollWidth <= chipsContainer.offsetWidth) return;
                            if (fontSize <= minFontSize) return;
                            fontSize = Math.max(minFontSize, fontSize - 0.04);
                            chips.forEach(c => {
                                c.style.fontSize = `${fontSize}rem`;
                                c.style.padding = `0.35rem ${0.7 + (fontSize - 0.62) * 0.6}rem`;
                            });
                            requestAnimationFrame(checkOverflow);
                        }
                        checkOverflow();
                    });
                }, 400);
            }
            
            // Initial render
            renderKeywordPage();
            
            // Start rotation every 6 seconds
            keywordRotationInterval = setInterval(renderKeywordPage, 6000);
            
        } catch (error) {
            console.error("Failed to load trending keywords:", error);
            updateTrendingStatus({ live: false, source: "unavailable" });
            chipsContainer.innerHTML = '<span class="text-muted" style="font-size:0.8rem;">Failed to load keywords.</span>';
        }
    }

    function updateTrendingStatus(data) {
        const badge = document.getElementById("trending-source-badge");
        if (!badge) return;
        const isLive = Boolean(data.live);
        const source = data.source || "Google News RSS";
        const fetchedAt = data.fetched_at ? new Date(data.fetched_at) : null;
        const timeLabel = fetchedAt && !Number.isNaN(fetchedAt.getTime())
            ? fetchedAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
            : "";
        badge.textContent = isLive
            ? `${source} · live${timeLabel ? ` · ${timeLabel}` : ""}`
            : `${source} · fallback`;
        badge.classList.toggle("live", isLive);
        badge.classList.toggle("fallback", !isLive);
    }

    // Start loading trending keywords immediately on load
    syncDetailsModalLayout();
    window.addEventListener("resize", syncDetailsModalLayout);
    if (window.visualViewport) {
        window.visualViewport.addEventListener("resize", syncDetailsModalLayout);
    }
    loadTrendingKeywords();

    // Refresh trending keywords every 5 minutes (300,000ms) from the server
    setInterval(() => {
        loadTrendingKeywords();
    }, 5 * 60 * 1000);
});
