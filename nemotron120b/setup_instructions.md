# OpenCode Setup Instructions for NVIDIA Nemotron 3 Super 120B

## Prerequisites

1. Node.js (v18 or higher)
2. npm or yarn
3. OpenRouter API key (get one from [openrouter.ai](https://openrouter.ai))

## Installation Steps

### 1. Install OpenCode CLI

```bash
npm install -g @opencode/ai
# or
yarn global add @opencode/ai
```

### 2. Configure OpenCode

Create the configuration directory if it doesn't exist:
```bash
mkdir -p ~/.config/opencode
```

Create or edit `~/.config/opencode/opencode.json` with the following configuration:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "model": "openrouter/nvidia/nemotron-3-super-120b-a12b:free",
  "provider": {
    "openrouter": {
      "name": "OpenRouter",
      "npm": "@ai-sdk/openai-compatible",
      "options": {
        "baseURL": "https://openrouter.ai/api/v1",
        "apiKey": "YOUR_OPENROUTER_API_KEY_HERE"
      },
      "models": {
        "nvidia/nemotron-3-super-120b-a12b:free": {
          "name": "nvidia/nemotron-3-super-120b-a12b:free",
          "tools": true
        }
      }
    }
  }
}
```

Replace `YOUR_OPENROUTER_API_KEY_HERE` with your actual OpenRouter API key.

### 3. Verify Installation

Test that OpenCode is properly installed and configured:

```bash
opencode --help
```

You should see the help output for the OpenCode CLI.

### 4. Using OpenCode with Nemotron 3 Super 120B

Once configured, you can start using OpenCode:

```bash
opencode
```

The model `nvidia/nemotron-3-super-120b-a12b:free` from OpenRouter will be used automatically based on your configuration.

## Additional Notes

- The Nemotron 3 Super 120B model is available for free on OpenRouter
- Make sure you have sufficient credits in your OpenRouter account
- The model supports tool usage as indicated in the configuration
- For optimal performance, ensure you have a stable internet connection

## Troubleshooting

If you encounter issues:

1. Verify your OpenRouter API key is correct
2. Check your internet connection
3. Ensure you have the latest version of OpenCode installed
4. Check that the model name matches exactly: `nvidia/nemotron-3-super-120b-a12b:free`

## Reference Configuration

This setup is based on the configuration found in `.config/opencode/opencode.json` which includes:
- OpenRouter provider configuration
- Proper baseURL for OpenRouter API
- Model specification for Nemotron 3 Super 120B
- Tool usage enabled for the model