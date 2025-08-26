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
- **Backend**: Flask-based plugin integrated with Airflow
- **Frontend**: HTML/CSS/JavaScript with Bootstrap styling
- **Storage**: Kubernetes ConfigMap (`airflow-config-pypi`)
- **Deployment**: Automatic pod restart via Kubernetes API

### Components Affected
When packages are modified, the following Airflow components are restarted:
- Worker pods
- Triggerer pods
- Scheduler pods

### Configuration
- **Namespace**: `data-orchestration` (configurable via environment variable)
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

## Support

For issues or questions:
1. Check the troubleshooting section
2. Review Airflow and Kubernetes logs
3. Contact the development team

## Changelog

### Version 2.0 (Current)
- ✅ Added package update functionality
- ✅ Improved package name validation
- ✅ Enhanced error handling
- ✅ Better user feedback

### Version 1.0
- ✅ Basic add/remove functionality
- ✅ Security features
- ✅ Kubernetes integration
