#!/usr/bin/env bash
set -e

# Default settings
IMAGE_NAME="${1:-lift-app:latest}"
NAMESPACE="lift-system"

echo "=========================================================="
echo "🏗️  1. Building Docker container image: ${IMAGE_NAME}"
echo "=========================================================="
docker build -t "${IMAGE_NAME}" .

# Check if using Minikube or Kind
if command -v minikube &> /dev/null && minikube status &> /dev/null; then
    echo "📦 Detected active Minikube cluster. Loading image into Minikube..."
    minikube image load "${IMAGE_NAME}"
elif command -v kind &> /dev/null && kind get clusters 2>&1 | grep -q 'kind'; then
    echo "📦 Detected active Kind cluster. Loading image into Kind..."
    kind load docker-image "${IMAGE_NAME}"
fi

echo ""
echo "=========================================================="
echo "🚀 2. Deploying manifests to Kubernetes namespace: ${NAMESPACE}"
echo "=========================================================="
kubectl apply -k k8s/

echo ""
echo "=========================================================="
echo "⏳ 3. Waiting for Redis to become Ready..."
echo "=========================================================="
kubectl rollout status statefulset/redis -n "${NAMESPACE}" --timeout=120s

echo ""
echo "=========================================================="
echo "⏳ 4. Waiting for Lift Services (16 Pods) to become Ready..."
echo "=========================================================="
kubectl rollout status statefulset/lift-service -n "${NAMESPACE}" --timeout=180s

echo ""
echo "=========================================================="
echo "⏳ 5. Waiting for Lift Orchestrator to become Ready..."
echo "=========================================================="
kubectl rollout status statefulset/lift-orchestrator -n "${NAMESPACE}" --timeout=120s

echo ""
echo "=========================================================="
echo "✅ All 16 Lifts, Orchestrator, and Redis are RUNNING!"
echo "=========================================================="
kubectl get pods -n "${NAMESPACE}"

echo ""
echo "🌐 Access the Web Dashboard:"
echo "   Run: kubectl port-forward -n ${NAMESPACE} svc/lift-orchestrator 8000:8000"
echo "   Open: http://localhost:8000"
echo "   (or via NodePort at http://<node-ip>:30080)"
echo "=========================================================="

