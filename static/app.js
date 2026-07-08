document.addEventListener("DOMContentLoaded", () => {
    const appRoot = document.getElementById("app-root");
    const logoHome = document.getElementById("logo-home");
    
    // Forms & Inputs
    const searchFormHeader = document.getElementById("search-form-header");
    const searchInputHeader = document.getElementById("search-input-header");
    const searchFormHero = document.getElementById("search-form-hero");
    const searchInputHero = document.getElementById("search-input-hero");
    
    const loadingState = document.getElementById("loading");
    const errorState = document.getElementById("error-state");
    const storiesContainer = document.getElementById("stories-container");
    const resultsMetaTabs = document.getElementById("results-meta-tabs");
    
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
    const modalVolatileList = document.getElementById("modal-volatile-list");
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

    // ── Settings & Model State ───────────────────────────────────────
    const settingsBtn    = document.getElementById("settings-btn");
    const settingsModal  = document.getElementById("settings-modal");
    const settingsSaveBtn   = document.getElementById("settings-save-btn");
    const settingsCancelBtn = document.getElementById("settings-cancel-btn");
    const settingsApiKey = document.getElementById("settings-api-key");
    const settingsModelName = document.getElementById("settings-model-name");
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

    // Model emoji labels for pill
    const PROVIDER_LABELS = {
        "dry-run": "🔬 Dry-Run",
        "openai":  "🤖 OpenAI",
        "gemini":  "💎 Gemini",
        "nim":     "⚡ NVIDIA NIM",
        "local":   "🖥️ Local",
    };

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
                await applyConfig(provider, "", model);
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
    function selectProvider(provider) {
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
    }

    providerGrid.querySelectorAll(".provider-card").forEach(card => {
        card.addEventListener("click", () => selectProvider(card.dataset.provider));
    });

    // Save button
    settingsSaveBtn.addEventListener("click", async () => {
        const providerCards = providerGrid.querySelectorAll(".provider-card.active");
        const provider = providerCards.length ? providerCards[0].dataset.provider : "dry-run";
        const apiKey   = settingsApiKey.value.trim();
        const model    = settingsModelName.value.trim();
        const activeCard = providerCards[0];
        const hasEnvKey  = activeCard && activeCard.querySelector(".key-badge");

        if ((provider === "openai" || provider === "gemini" || provider === "nim") && !apiKey && !hasEnvKey) {
            showStatus("error", "Please enter an API key for this provider.");
            return;
        }

        settingsSaveBtn.setAttribute("loading", "");
        const ok = await applyConfig(provider, apiKey, model);
        settingsSaveBtn.removeAttribute("loading");

        if (ok) {
            showStatus("success", "✓ Settings saved! AI provider is now active.");
            setTimeout(() => settingsModal.hide(), 1200);
        } else {
            showStatus("error", "Failed to save settings. Check the server.");
        }
    });

    function showStatus(type, msg) {
        settingsStatus.textContent = msg;
        settingsStatus.className = `settings-status ${type}`;
        settingsStatus.classList.remove("hidden");
    }

    async function applyConfig(provider, apiKey, model) {
        try {
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
        } catch { return false; }
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
            activeModel    = cfg.model    || "";
            updateProviderBadge(activeProvider, activeModel);
            // Pre-select correct provider card in modal
            selectProvider(activeProvider);
            if (activeModel) settingsModelName.value = activeModel;

            // Mark provider cards that have keys already in .env with a ✓
            keysPresent = cfg.keys_present || {};
            markProviderKeys(keysPresent);
        } catch {}
    }
    initConfig();

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
        errorState.classList.add("hidden");
        modal.hide();
        loadTrendingKeywords();
    });

    async function performSearch(query) {
        // Synchronize inputs
        searchInputHero.value = query;
        searchInputHeader.value = query;

        // Transition states
        appRoot.classList.remove("initial-state");
        appRoot.classList.add("results-state");

        // Show Loading, Hide contents
        loadingState.classList.remove("hidden");
        errorState.classList.add("hidden");
        storiesContainer.classList.add("hidden");
        resultsMetaTabs.classList.add("hidden");
        
        leftColumnCards.innerHTML = "";
        centerColumnCards.innerHTML = "";
        rightColumnCards.innerHTML = "";
        
        try {
            const response = await fetch(`/api/search?q=${encodeURIComponent(query)}&limit=10`);
            const data = await readApiResponse(response);
            
            // Keep the visible model pill in sync with the backend response.
            if (data.provider) {
                activeProvider = data.provider;
                activeModel = data.model || "";
                updateProviderBadge(activeProvider, activeModel);
            }
            
            currentClustersData = data.clusters || [];
            
            if (currentClustersData.length === 0) {
                showEmptyState("No matching stories found.", "Try searching for another topic or simplify your keywords.");
            } else {
                renderClusters(currentClustersData);
                applyTabFilter(currentTab);
                loadingState.classList.add("hidden");
                storiesContainer.classList.remove("hidden");
                resultsMetaTabs.classList.remove("hidden");
            }
        } catch (error) {
            console.error("Search failed:", error);
            showEmptyState("An error occurred during search.", error.message || "Please check the server connection and configurations, then try again.");
        }
    }

    function showEmptyState(title, subtitle) {
        loadingState.classList.add("hidden");
        storiesContainer.classList.add("hidden");
        resultsMetaTabs.classList.add("hidden");
        errorState.classList.remove("hidden");
        
        errorState.querySelector("h2").textContent = title;
        errorState.querySelector("p").textContent = subtitle;
    }

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
        const headline = cluster.analysis.headline || cluster.articles[0].title;
        const sourceCount = cluster.source_count;
        const dist = cluster.trust_distribution;
        const status = cluster.trust_status;
        const volatile = cluster.analysis.volatile_elements || [];
        const conflictCount = volatile.length;
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

        const imgHTML = imageUrl
            ? `<img class="story-card-img" src="${escapeHTML(imageUrl)}" alt="" loading="lazy" onerror="this.style.display='none'; this.parentElement.querySelector('.story-img-fallback').style.display='flex';">`
            : "";
        const fallbackHTML = `<div class="story-img-fallback" style="display:${imageUrl ? 'none' : 'flex'}"><i class="fa-regular fa-image"></i></div>`;

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

        // Render Banner Image in Modal
        const validArticle = cluster.articles.find(a => a.image_url && !a.image_url.includes("favicon")) || cluster.articles[0];
        const imageUrl = validArticle ? validArticle.image_url : "";
        const modalBanner = document.getElementById("modal-banner");
        if (imageUrl) {
            modalBanner.innerHTML = `<img src="${escapeHTML(imageUrl)}" alt="" onerror="this.parentElement.classList.add('hidden')" style="width:100%;height:100%;object-fit:cover;display:block;">`;
            modalBanner.style.backgroundImage = "";
            modalBanner.classList.remove("hidden");
        } else {
            modalBanner.classList.add("hidden");
        }

        // Volatile conflicts
        modalVolatileList.innerHTML = "";
        const volatile = cluster.analysis.volatile_elements || [];
        if (volatile.length === 0) {
            modalVolatileList.innerHTML = "<li>No conflicting details detected. All sources provide corroborating information.</li>";
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
        const notes = cluster.analysis.source_notes || [];
        if (notes.length === 0) {
            modalNotesList.innerHTML = "<li>No additional source analysis notes available.</li>";
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

        modal.show();
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
            chipsContainer.innerHTML = '<span class="text-muted" style="font-size:0.8rem;">Failed to load keywords.</span>';
        }
    }

    // Start loading trending keywords immediately on load
    loadTrendingKeywords();
});
