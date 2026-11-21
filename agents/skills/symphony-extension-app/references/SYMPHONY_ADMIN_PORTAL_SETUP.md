# Symphony Pod Admin Console: Bot & App Setup Guide

This guide details the exact manual steps required in the **Symphony Admin Console (Pod Management Portal)** to register a **Bot Service Account** and an **Extension Application** with Circle of Trust (CoT).

---

## 🔑 Step 0: Generate the RSA Key Pair

Both the Bot Service Account and the Extension Application authenticate to the Symphony Pod using an RSA key pair. While you can use separate key pairs, using a shared key pair simplifies deployment and secret management.

Run in your terminal:
```bash
# Generate 4096-bit RSA private key
openssl genrsa -out app-bot-private-key.pem 4096

# Extract the public key in PEM format
openssl rsa -in app-bot-private-key.pem -pubout -out app-bot-public-key.pem
```

- **`app-bot-public-key.pem`**: Uploaded to the Symphony Admin Console for both the Service Account and the Application.
- **`app-bot-private-key.pem`**: Kept confidential. Added as a GitHub Secret (`BOT_RSA_PRIVATE_KEY`) and mounted in the Kubernetes container (`/app/secrets/{{APP_ID}}-private-key.pem`).

---

## 🤖 Step 1: Create the Bot Service Account

A Bot Service Account is required if the MCP server needs to send messages to Symphony chats/rooms, create 1-to-1 IMs, or make backend calls via the Symphony REST API / BDK.

1. Navigate to your pod's Admin Console:
   `https://<POD_HOST>/admin-console` (e.g. `https://sym-market-solutions.on.uat.symphony.com/admin-console`)
2. In the left navigation, go to **Accounts** → **Service Accounts**.
3. Click **Create Service Account** (or **Add User** → **Service Account**).
4. Fill in the required fields:
   - **Account Type**: `Service Account` / `Bot`
   - **User Name / Account Name**: e.g. `{{APP_ID}}-bot` (Record this as `SYMPHONY_BOT_USERNAME`)
   - **Display Name**: e.g. `{{APP_TITLE}} Bot`
   - **Email Address**: e.g. `{{APP_ID}}-bot@<pod-domain>`
   - **Department / Company**: e.g. `Professional Services`
5. **Roles & Entitlements**:
   - Check **Service Account** role.
   - Under **Features / Entitlements**, ensure:
     - `Can Create IM`
     - `Can Search Directory`
     - `Can Create Public Room` / `Can Create Private Room` (if required)
6. **Authentication / RSA Public Key**:
   - Under Authentication Type, select **RSA**.
   - Click **Upload Public Key** (or paste contents of `app-bot-public-key.pem`).
   - Save the service account.
7. **Record Bot Info**:
   - Note the **Numeric User ID** (visible in URL or user list, e.g. `353569724123456`).

---

## 📱 Step 2: Register the Extension Application (UI Module)

The Extension Application registration controls how Symphony renders the left-nav icon, loads the iframe controller, and manages user identity via Circle of Trust.

1. In the Admin Console, go to **Applications** → **App Management** (or **Marketplace / Applications**).
2. Click **Add an Application** (or **Install Custom Application** / **Create Application**).
3. Fill in the **Application Descriptor / Properties**:
   - **Application ID (`appGroupId`)**: e.g. `{{APP_ID}}`
     ⚠️ **CRITICAL**: This value MUST match:
     - `id` passed to `ADK.start({ id: "{{APP_ID}}", circleOfTrust })` in `controller.js`
     - `id` passed to `ADK.connectView({ id: "{{APP_ID}}" })` in `view.js`
     - `applications[0].id` and `applications[0].appGroupId` in `bundle.json`
     - Environment variable `SYMPHONY_APP_ID={{APP_ID}}`
   - **Application Name**: `{{APP_TITLE}}` (human-friendly app title)
   - **Description**: Brief explanation of the app's function.
   - **Publisher**: `Symphony Market Solutions` or `Symphony Professional Services`
   - **Domain**: `mss.uat.symphony.com`
     ⚠️ Only the fully qualified hostname serving your app without protocol (`https://`) or trailing path.
   - **Load URL / Controller URL**:
     `https://mss.uat.symphony.com/mcp/{{APP_ID}}/v1/app/controller.html`
   - **Icon URL**:
     `https://mss.uat.symphony.com/mcp/{{APP_ID}}/v1/app/icon.svg`
4. **Permissions & Entitlements**:
   - Check **`TRUST_APP`** (Circle of Trust) — **MANDATORY** for user identity exchange.
   - Check `can_create_im` / `send_message` / `can_post_message` if prompted.
5. **RSA Public Key (Circle of Trust)**:
   - Paste or upload the public key from `app-bot-public-key.pem`.
     (In the raw JSON bundle, this populates the `rsaKey` block).
6. **Application Visibility / Scope**:
   - Under **Availability**, select **"Available to all users in the pod"** (or assign to specific entitlement groups/companies).
   - If not set to all users, the app will NOT appear in the left navigation bar for standard users.
7. Click **Save / Install Application**.

---

## 🔄 Step 3: Wire Credentials into the MCP Project

Once the Bot and App are registered in the Symphony Pod:

| Symphony Field | Destination in MCP Server | Purpose |
|---|---|---|
| **Application ID** (`{{APP_ID}}`) | `SYMPHONY_APP_ID` in `.env`, `k8s/dev/deployment-patch.yml` | Matches ADK handshake and pod token minting |
| **Pod Host** (`sym-market-solutions.on.uat.symphony.com`) | `SYMPHONY_POD_HOST` in `.env`, `k8s/dev/deployment-patch.yml` | Target host for pod cert and authentication endpoints |
| **RSA Private Key** (`app-bot-private-key.pem`) | GitHub Secret `BOT_RSA_PRIVATE_KEY` → K8s secret `{{APP_ID}}-credentials` | Signs app JWT to mint $T_s$ and authenticates Bot REST calls |
| **Bot Username** (`{{APP_ID}}-bot`) | `SYMPHONY_BOT_USERNAME` in `.env` | Used by BDK/REST client for message attribution |
| **Bot Numeric ID** (`353569...`) | `SYMPHONY_BOT_USER_ID` in `.env` | Used to filter out bot's own messages in room listeners |

---

## 🧪 Step 4: Verification Checklist

1. **Verify Pod Reachability**:
   ```bash
   curl -s "https://<POD_HOST>/pod/v1/podcert" | jq .
   ```
   Should return `{"certificate": "-----BEGIN CERTIFICATE...-----"}`.
2. **Reload Symphony Client**:
   - Hard-reload Symphony desktop or web client (`Cmd+Shift+R` or `Ctrl+F5`).
   - Check the left-hand navigation bar for the app icon.
   - Open Developer Tools (`Cmd+Option+I` or right-click → Inspect).
   - Check console logs for:
     ```
     [App] CoT: obtained app token (Ta)
     [App] CoT: token pair validated
     [App] CoT: user JWT verified, userId=...
     [App] ADK connected to Symphony client
     [App] Left-nav item added
     [View] Connected to Symphony client
     ```
