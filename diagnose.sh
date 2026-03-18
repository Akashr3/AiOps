# Copy and run the diagnostic script
bash <(cat <<'EOF'
#!/bin/bash

echo "========================================="
echo "1. FILEBEAT POD STATUS"
echo "========================================="
kubectl get pods -n kube-system -l k8s-app=filebeat

echo ""
echo "========================================="
echo "2. APPLICATION PODS STATUS"
echo "========================================="
kubectl get pods | grep -E "(catalog|gateway|orders|payments|users)"

echo ""
echo "========================================="
echo "3. FILES FILEBEAT CAN SEE"
echo "========================================="
FILEBEAT_POD=$(kubectl get pod -n kube-system -l k8s-app=filebeat -o jsonpath='{.items[0].metadata.name}')
echo "Filebeat pod: $FILEBEAT_POD"
echo ""
echo "Total container log files:"
kubectl exec -n kube-system $FILEBEAT_POD -- ls /var/log/containers/ | wc -l
echo ""
echo "Application service logs:"
kubectl exec -n kube-system $FILEBEAT_POD -- ls -la /var/log/containers/ | grep -E "(catalog|gateway|orders|payments|users)"

echo ""
echo "========================================="
echo "4. SAMPLE LOG CONTENT"
echo "========================================="
echo "Catalog log sample:"
kubectl exec -n kube-system $FILEBEAT_POD -- sh -c 'cat /var/log/containers/catalog-*.log 2>/dev/null | head -2'

echo ""
echo "========================================="
echo "5. FILEBEAT CURRENT CONFIG (from pod)"
echo "========================================="
kubectl exec -n kube-system $FILEBEAT_POD -- cat /etc/filebeat.yml

echo ""
echo "========================================="
echo "6. FILEBEAT METRICS"
echo "========================================="
kubectl logs -n kube-system -l k8s-app=filebeat --tail=100 | grep "Non-zero metrics" | tail -1

echo ""
echo "========================================="
echo "7. FILEBEAT ERRORS"
echo "========================================="
kubectl logs -n kube-system -l k8s-app=filebeat --tail=200 | grep -i error | tail -10

echo ""
echo "========================================="
echo "8. CHECK WHAT FILEBEAT IS HARVESTING"
echo "========================================="
kubectl logs -n kube-system -l k8s-app=filebeat | grep -i "harvester" | tail -10

echo ""
echo "========================================="
echo "DIAGNOSTIC COMPLETE"
echo "========================================="
EOF
)

