# Airflow Package Manager Plugin

A Flask-based plugin for Apache Airflow that provides a web interface to manage Python packages in the Airflow environment. This plugin allows administrators to add, remove, and update Python packages without manually editing configuration files or rebuilding Docker images.

## Features

### 🔧 Package Management
- **Add Packages**: Install new Python packages with version specifications
- **Remove Packages**: Uninstall packages from the Airflow environment
- **Update Packages**: Update package versions without removing and re-adding (NEW!)

### 🔒 Security Features
- CSRF protection for all operations
- Token-based operation verification
- User authentication and authorization
- Audit logging for all package operations

### 🚀 Automated Deployment
- Automatic Kubernetes ConfigMap updates
- Automatic Airflow component restart (Worker, Triggerer, Scheduler)
- Real-time status feedback

## Installation

The plugin is automatically installed with the Airflow Docker image. No additional setup required.

## Usage

### Accessing the Package Manager

1. Navigate to your Airflow web interface
2. Go to **Admin** → **Package Manager** in the navigation menu
3. You'll see the package management interface

### Adding a Package

1. Enter the package name with version in the "Add New Package" form
   - Example: `pandas==1.5.0`
   - Example: `requests>=2.25.0`
   - Example: `numpy` (latest version)
2. Click "Add Package"
3. The system will:
   - Validate the package name
   - Add it to the requirements.txt ConfigMap
   - Restart Airflow components
   - Show success/error messages

### Updating a Package

1. Find the package you want to update in the "Installed Packages" table
2. Click the "Update" button (yellow button)
3. In the modal that appears:
   - The current package version is shown
   - Enter the new package version
   - Click "Update Package"
4. The system will:
   - Validate the new package version
   - Update the package in the ConfigMap
   - Restart Airflow components
   - Show success/error messages

### Removing a Package

1. Find the package you want to remove in the "Installed Packages" table
2. Click the "Remove" button (red button)
3. Confirm the removal in the dialog
4. The system will:
   - Remove the package from the ConfigMap
   - Restart Airflow components
   - Show success/error messages

## Package Version Formats

The plugin supports standard pip version specifications:

- `package==1.0.0` - Exact version
- `package>=1.0.0` - Minimum version
- `package<=1.0.0` - Maximum version
- `package>1.0.0` - Greater than version
- `package<1.0.0` - Less than version
- `package~=1.0.0` - Compatible release
- `package!=1.0.0` - Exclude version
- `package` - Latest version

## Security Considerations

### Token-Based Operations
All package operations require a secure token that:
- Expires after 1 hour
- Is tied to the specific user and operation
- Can only be used once
- Prevents CSRF attacks

### User Permissions
Only users with `Admin` permissions can:
- View the package list
- Add packages
- Update packages
- Remove packages

### Audit Logging
All package operations are logged with:
- User information
- IP address
- Timestamp
- Operation details

## Technical Details

### Architecture
- **Backend**: Flask-based plugin integrated with Airflow (`__init__.py` view + `k8s_rollout.py` helpers)
- **Frontend**: HTML/CSS/JavaScript with Bootstrap styling
- **Storage**: Kubernetes ConfigMap (`airflow-config-pypi`)
- **Deployment**: Rolling restart via `kubectl rollout restart` (no scale-down)

### Restart Mechanism (rolling restart, no downscale)
When packages are modified, the plugin runs the equivalent of:

```
kubectl rollout restart deployment,statefulset -l 'component in (worker,triggerer,scheduler)' -n <namespace>
```

This patches each workload's pod template with a restart annotation, so Kubernetes
recreates pods **gradually while preserving the configured replica count**. Your
4 workers stay 4 — they are *not* scaled to zero. Running tasks drain during the
rolling restart instead of being killed by a full outage.

> **Previous behaviour (removed):** the plugin used to scale every component to
> `0` and back up. A bug captured the replica count *after* setting it to `0`, so
> components always came back up at `1` replica regardless of their real size
> (e.g. 4 workers → 0 → 1). The rolling-restart approach fixes both the outage and
> the replica loss.

### Components Affected
Matched by the `component` label, restarted in place:
- Worker pods (`component=worker`)
- Triggerer pods (`component=triggerer`)
- Scheduler pods (`component=scheduler`)

### Previous State & Rollback
- Before each change, the prior `requirements.txt` and the current replica/rollout
  state are captured.
- The prior requirements are stored as ConfigMap annotations:
  `fast.bi/previous-requirements`, `fast.bi/last-modified-by`, `fast.bi/last-modified-at`.
- The UI shows a **Previous State** panel and a **Roll back** button that restores
  the prior requirements and triggers another rolling restart.
- A **Restart Status** panel polls `GET /package-manager/status` to show per-component
  rollout progress (ready / updated replicas) live.

### Cluster-side requirements (apply in the infra repo)
These live in `data-platform-infrastructure-deployment-files`, **not** in this image:

1. **RBAC** — the Airflow ServiceAccount used by the webserver needs permission to
   patch workloads and read their status. Example `Role` rules:

   ```yaml
   rules:
     - apiGroups: [""]
       resources: ["configmaps"]
       verbs: ["get", "patch"]
     - apiGroups: ["apps"]
       resources: ["deployments", "statefulsets"]
       verbs: ["get", "list", "patch"]   # patch is required for rollout restart
     - apiGroups: ["apps"]
       resources: ["deployments/scale", "statefulsets/scale"]
       verbs: ["get"]                      # scale verb no longer needs patch
   ```

   Without the `patch` verb on `deployments`/`statefulsets`, the rollout returns
   `403 Forbidden`.

2. **StatefulSet update strategy** must be `RollingUpdate` (the default) for
   `kubectl rollout restart` to act on workers/triggerer. Verify with:

   ```
   kubectl get statefulset -l 'component in (worker,triggerer)' -n <ns> \
     -o jsonpath='{range .items[*]}{.metadata.name}{": "}{.spec.updateStrategy.type}{"\n"}{end}'
   ```

   Any component on `OnDelete` will not be restarted by rollout restart.

3. **kubectl** must be present in the image (it is — installed via the gcloud SDK
   in the Dockerfile).

### Configuration
- **Namespace**: `data-orchestration` (env `AIRFLOW__KUBERNETES_ENVIRONMENT_VARIABLES__AIRFLOW_NAMESPACE`)
- **ConfigMap**: `airflow-config-pypi`
- **Token Expiry**: 1 hour

## Troubleshooting

### Common Issues

1. **"Invalid or expired token" error**
   - Token expiry has been extended to 1 hour
   - If you still experience issues, try refreshing the page
   - Check browser console for debugging information
   - Ensure you're logged in with proper permissions

2. **Package not found during update**
   - Ensure the package exists in the current list
   - Check for typos in the package name

3. **Invalid package name**
   - Use only alphanumeric characters, hyphens, underscores, and dots
   - Follow pip package naming conventions

4. **Operation failed**
   - Check Airflow logs for detailed error messages
   - Verify Kubernetes cluster connectivity
   - Ensure proper permissions

5. **Components not restarting**
   - Check Kubernetes cluster status
   - Verify namespace and ConfigMap exist
   - Check for resource constraints

### Logs
Package manager operations are logged in:
- Airflow web server logs
- Kubernetes pod logs
- Application logs with user context

## Development

### Adding New Features
1. Extend the `PackageManagerView` class
2. Add new endpoints with proper CSRF protection
3. Update the frontend template
4. Add appropriate error handling
5. Update this documentation

### Testing
- Test with various package formats
- Verify security measures
- Test error conditions
- Validate Kubernetes integration
- Run the dependency-free unit tests: `pytest tests/test_k8s_rollout.py`
  (these cover the kubectl arg construction, JSON parsing, and rollout-state
  logic without needing Airflow/Flask/kubernetes installed)

## Support

For issues or questions:
1. Check the troubleshooting section
2. Review Airflow and Kubernetes logs
3. Contact the development team

## Changelog

### Version 3.0 (Current)
- ✅ **Rolling restart instead of scale-to-zero** — replica counts are preserved (no more 4→0→1 downscale), no full outage
- ✅ Restart now uses `kubectl rollout restart` (kubectl shipped in the image)
- ✅ Previous-state capture (prior requirements + replica state) stored as ConfigMap annotations
- ✅ New `GET /status` endpoint + live Restart Status panel
- ✅ New `POST /rollback` endpoint + UI button to restore previous requirements
- ✅ Extracted rollout logic into dependency-free `k8s_rollout.py` with unit tests
- ✅ Simplified token storage (single module store + session fallback); removed unused imports

### Version 2.0
- ✅ Added package update functionality
- ✅ Improved package name validation
- ✅ Enhanced error handling
- ✅ Better user feedback

### Version 1.0
- ✅ Basic add/remove functionality
- ✅ Security features
- ✅ Kubernetes integration
