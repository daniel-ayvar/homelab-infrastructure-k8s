Flux Reconcile + Deployment Debug Steps

Reconcile flow (apps blocked or changes not applying)
1) Check Flux status:
   - kubectl get kustomizations -n flux
2) If apps are blocked, force namespaces then apps:
   - kubectl annotate kustomization flux-sync-namespaces -n flux reconcile.fluxcd.io/requestedAt="$(date -u +%Y-%m-%dT%H:%M:%SZ)" --overwrite
   - kubectl annotate kustomization flux-sync-apps -n flux reconcile.fluxcd.io/requestedAt="$(date -u +%Y-%m-%dT%H:%M:%SZ)" --overwrite
3) Verify reconciliation details:
   - kubectl describe kustomization flux-sync-apps -n flux

Deployment + ConfigMap sanity checks (code/config not updating)
1) Find the current ConfigMap name:
   - kubectl get configmaps -n <namespace> | rg -n "<app-name>"
2) Inspect ConfigMap content for expected changes:
   - kubectl get configmap -n <namespace> <configmap-name> -o yaml
3) Restart the workload to pick up new ConfigMap:
   - kubectl rollout restart -n <namespace> deployment/<deployment-name>
4) Confirm rollout:
   - kubectl rollout status -n <namespace> deployment/<deployment-name> --timeout=120s
5) Validate the service output (example with port-forward + curl):
   - kubectl -n <namespace> port-forward svc/<service-name> 18081:<port>
   - curl -sS http://127.0.0.1:18081/<path>

