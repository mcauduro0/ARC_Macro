# ARC Macro Risk OS — GPU Droplet Setup Guide

This guide explains how to set up a DigitalOcean GPU Droplet for accelerated model execution.

## Architecture

The pipeline is split into two phases:

| Phase | Where | Duration | Purpose |
|-------|-------|----------|---------|
| **Data Collection** | GH Actions | ~10-15 min | Fetch BCB, FRED, TE, ANBIMA, IPEADATA |
| **Model Execution** | DO GPU Droplet | ~15-20 min | Feature Selection, PCA/VAR, Stability Selection |

Total: ~25-35 min (vs ~2h on GH Actions CPU-only runner).

## Prerequisites

1. A DigitalOcean GPU Droplet (recommended: GPU Basic, 1x NVIDIA H100 or A100)
2. SSH access configured
3. Python 3.11+ installed

## Step 1: Provision the Droplet

```bash
# Create a GPU droplet via DO CLI or Console
doctl compute droplet create arc-macro-gpu \
  --size gpu-h100x1-80gb \
  --image ubuntu-22-04-x64 \
  --region nyc1 \
  --ssh-keys <your-ssh-key-id>
```

## Step 2: Install Dependencies

SSH into the droplet and run:

```bash
# Update system
apt update && apt upgrade -y

# Install Python 3.11
apt install -y python3.11 python3.11-venv python3-pip git

# Clone the repository
git clone https://github.com/mcauduro0/ARC_Macro.git /opt/ARC_Macro
cd /opt/ARC_Macro/server/model

# Install Python dependencies
pip install -r requirements.txt

# Verify numpy uses GPU-accelerated BLAS
python3.11 -c "import numpy; numpy.show_config()"
```

## Step 3: Configure GitHub Secrets

Add these secrets to the repository (`Settings → Secrets → Actions`):

| Secret | Description | Example |
|--------|-------------|---------|
| `DO_GPU_SSH_KEY` | Private SSH key for the droplet | `-----BEGIN OPENSSH PRIVATE KEY-----...` |
| `DO_GPU_HOST` | Droplet IP address | `143.198.xxx.xxx` |
| `DO_GPU_USER` | SSH user | `root` |

## Step 4: Test Locally

```bash
# On the droplet, test the model runner
cd /opt/ARC_Macro/server/model
export MANUS_WEBHOOK_SECRET="your-secret"
export MANUS_DASHBOARD_URL="https://your-dashboard.manus.space"
bash do_gpu_runner.sh
```

## Step 5: Trigger GPU Workflow

From GitHub Actions, manually trigger "BRLUSD Model Run (GPU Accelerated)".

## Performance Comparison

| Metric | GH Actions (CPU) | DO GPU Droplet |
|--------|-------------------|----------------|
| Data Collection | ~10-15 min | N/A (done on GH) |
| Model Execution | ~90-120 min | ~15-20 min |
| **Total** | **~100-135 min** | **~25-35 min** |
| Cost | Free (GH Actions) | ~$2.50/hr GPU |

## Cost Optimization

The GPU droplet only needs to run during model execution (~20 min/day). Use the DO API to:

1. **Power on** the droplet before the model run
2. **Run the model**
3. **Power off** the droplet after completion

This reduces cost to ~$0.85/day (~$25/month) instead of running 24/7.

```bash
# Power on before run
doctl compute droplet-action power-on <droplet-id>

# Wait for boot
sleep 60

# Run model
ssh root@<droplet-ip> "cd /opt/ARC_Macro/server/model && bash do_gpu_runner.sh"

# Power off after run
doctl compute droplet-action power-off <droplet-id>
```

## Troubleshooting

- **SSH timeout**: Ensure the droplet is powered on and security group allows port 22
- **Python version**: The model requires Python 3.11+
- **Missing data**: If no `--data-tar` is passed, the model uses local cached CSVs
- **Webhook failure**: Check `MANUS_WEBHOOK_SECRET` and `MANUS_DASHBOARD_URL` are correct
