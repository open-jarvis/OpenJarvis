	FROM python:3.12-slim
	WORKDIR /app
	# ── System packages ────────────────────────────────────────────────────────────
	RUN apt-get update && apt-get install -y --no-install-recommends \
	    nginx supervisor git curl gnupg ca-certificates gettext-base openssh-client \
	    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
	    && apt-get install -y nodejs \
	    && apt-get clean && rm -rf /var/lib/apt/lists/*
	# ── GitHub CLI (gh) ───────────────────────────────────────────────────────────
	RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
	    -o /usr/share/keyrings/githubcli-archive-keyring.gpg \
	    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
	    > /etc/apt/sources.list.d/github-cli.list \
	    && apt-get update && apt-get install -y gh \
	    && apt-get clean && rm -rf /var/lib/apt/lists/*
	# ── code-server (VSCode in browser) ───────────────────────────────────────────
	RUN curl -fsSL https://code-server.dev/install.sh | sh
	# ── Global CLIs (Claude, Gemini, Railway) ─────────────────────────────────────
	RUN npm install -g @anthropic-ai/claude-code @google/gemini-cli @railway/cli
	# ── VS Code extensions ────────────────────────────────────────────────────────
	RUN code-server --install-extension GitHub.vscode-pull-request-github \
	    && code-server --install-extension eamodio.gitlens \
	    && code-server --install-extension Anthropic.claude-code
	# ── Java + Android tools ─────────────────────────────────────────────────────
	RUN apt-get update && apt-get install -y --no-install-recommends default-jdk-headless unzip xz-utils zip \
	    && rm -rf /var/lib/apt/lists/*
	RUN JAVA_BIN=$(readlink -f $(which java)) && echo "JAVA_HOME=$(dirname $(dirname $JAVA_BIN))" >> /etc/ environment
	ENV JAVA_HOME=/usr/lib/jvm/default-java
	# ── Flutter SDK ──────────────────────────────────────────────────────────────
	ENV FLUTTER_VERSION=3.27.4
	ENV FLUTTER_HOME=/opt/flutter
	ENV PATH="${FLUTTER_HOME}/bin:${PATH}"
	RUN curl -fsSL --retry 3 "https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/flutter_linux_${FLUTTER_VERSION}-stable.tar.xz" \
	    | tar xJ -C /opt/ \
	    && git config --global --add safe.directory /opt/flutter \
	    && /opt/flutter/bin/flutter config --no-analytics
	# ── Android SDK ──────────────────────────────────────────────────────────────
	ENV ANDROID_HOME=/opt/android-sdk
	ENV ANDROID_SDK_ROOT=/opt/android-sdk
	ENV PATH="${ANDROID_HOME}/cmdline-tools/latest/bin:${ANDROID_HOME}/platform-tools:${PATH}"
	RUN mkdir -p ${ANDROID_HOME}/cmdline-tools \
	    && curl -fsSL https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip -o /tmp/cmdtools.zip \
	    && unzip -q /tmp/cmdtools.zip -d /tmp/cmdtools \
	    && mv /tmp/cmdtools/cmdline-tools ${ANDROID_HOME}/cmdline-tools/latest \
	    && rm -rf /tmp/cmdtools /tmp/cmdtools.zip \
	    && yes | sdkmanager --licenses \
	 && sdkmanager "platforms; android-34"  "build-tools; 34.0.0"  "platform-tools" \
	    && flutter config --android-sdk ${ANDROID_HOME}
	RUN code-server --install-extension Dart-Code.dart-code Dart-Code.flutter
	# ── Python dependencies ───────────────────────────────────────────────────────
	COPY requirements.txt .
	RUN pip install --no-cache-dir -r requirements.txt
	# ── Playwright + Camoufox ────────────────────────────────────────────────────
	RUN playwright install --with-deps chromium firefox \
	    && python -m camoufox fetch
	# ── OpenJarvis Integration ────────────────────────────────────────────────────
	RUN git clone https://github.com/open-jarvis/OpenJarvis.git /app/jarvis
	WORKDIR /app/jarvis
	RUN pip install --no-cache-dir -r requirements.txt
	WORKDIR /app/jarvis/web
	RUN npm install && npm run build
	WORKDIR /app
	# ── Orchestrator & API Layer ──────────────────────────────────────────────────
	COPY orchestrator/ /app/orchestrator/
	COPY start.py /app/start.py
	# ── Application source & Configs ──────────────────────────────────────────────
	COPY . .
	COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
	COPY nginx.conf.template /app/nginx.conf.template
	# ── Workspace & Permissions ───────────────────────────────────────────────────
	RUN mkdir -p /workspace /workspace/.vscode /workspace/.vscode-ext /var/log/supervisor \
	    && mkdir -p /root/.claude && chmod 700 /root/.claude \
	    && mkdir -p /root/.gemini && chmod 700 /root/.gemini
	COPY entrypoint.sh /app/entrypoint.sh
	RUN sed -i 's/\r//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh
	EXPOSE 8000
	CMD ["/app/entrypoint.sh"]
