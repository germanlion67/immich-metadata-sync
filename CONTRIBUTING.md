# Contributing to IMMICH ULTRA-SYNC

Thank you for your interest in contributing to IMMICH ULTRA-SYNC! This document provides guidelines and information to help you contribute effectively.

## Table of Contents
- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Project Structure](#project-structure)
- [Making Changes](#making-changes)
- [Testing](#testing)
- [Code Style](#code-style)
- [Submitting Changes](#submitting-changes)
- [Reporting Issues](#reporting-issues)

## Code of Conduct

We are committed to providing a welcoming and inclusive environment. Please be respectful and constructive in all interactions.

## Getting Started

1. **Fork the repository** on GitHub
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/YOUR-USERNAME/immich-metadata-sync.git
   cd immich-metadata-sync
   ```
3. **Create a branch** for your changes:
   ```bash
   git checkout -b feature/your-feature-name
   ```

## Development Setup

### Prerequisites
- Python 3.11 or higher
- ExifTool (for metadata operations)
- Docker (optional, for testing containerized deployments)

### Installing Dependencies
```bash
pip install -r requirements.txt
```

### Running the Script Locally
```bash
cd script
python3 immich-ultra-sync.py --help
```

## Project Structure

```
immich-metadata-sync/
├── script/                    # Main application code
│   ├── immich-ultra-sync.py  # Main orchestration script
│   ├── api.py                # Immich API interactions
│   ├── exif.py               # EXIF/XMP metadata operations
│   ├── utils.py              # Utility functions and helpers
│   └── healthcheck.py        # Health check utilities
├── tests/                     # Test suite
│   ├── test_immich_ultra_sync.py
│   └── test_metadata_sync.py
├── doc/                       # Documentation
│   ├── de/                   # German documentation
│   └── immich-metadata-sync.md
├── requirements.txt           # Python dependencies
├── Dockerfile                 # Container image definition
├── VERSION                    # Current version
└── CHANGELOG.md              # Version history
```

## Making Changes

### Guidelines
1. **Keep changes focused**: Each PR should address a single feature or bug fix
2. **Maintain backward compatibility**: Ensure existing functionality continues to work
3. **Update documentation**: Update relevant docs when adding features or changing behavior
4. **Add tests**: Include tests for new features or bug fixes
5. **Follow the existing code style**: Consistency is important

### Key Principles
- **Minimal changes**: Make the smallest possible changes to achieve your goal
- **Security first**: Never commit secrets or credentials
- **Error handling**: Add appropriate error handling and logging
- **Performance**: Consider performance implications of your changes

## Testing

### Running Tests
```bash
# Run all tests
python3 -m pytest tests/ -v

# Run with coverage
python3 -m pytest tests/ --cov=script --cov-report=html

# Run specific test file
python3 -m pytest tests/test_immich_ultra_sync.py -v
```

### Writing Tests
- Place tests in the `tests/` directory
- Use descriptive test names that explain what is being tested
- Follow the existing test structure and conventions
- Test both success and failure cases
- Mock external dependencies (API calls, file system operations)

### Test Coverage
We aim for high test coverage. Please ensure your changes include appropriate tests.

## Code Style

### Python Style
- Follow [PEP 8](https://peps.python.org/pep-0008/) guidelines
- Use meaningful variable and function names
- Add docstrings for functions and classes
- Keep functions focused and concise
- Use type hints where appropriate

### Documentation Style
- Use clear, concise language
- Include code examples where helpful
- Update the CHANGELOG.md for user-facing changes
- Keep README.md up to date with new features

### Comments
- Add comments for complex logic
- Avoid obvious comments
- Use comments to explain "why", not "what"
- Keep comments up to date with code changes

## Submitting Changes

### Pull Request Process

1. **Update your branch** with the latest changes from main:
   ```bash
   git checkout main
   git pull origin main
   git checkout your-feature-branch
   git rebase main
   ```

2. **Run tests** to ensure everything works:
   ```bash
   python3 -m pytest tests/ -v
   ```

3. **Commit your changes** with clear, descriptive messages:
   ```bash
   git add .
   git commit -m "Add feature: description of your changes"
   ```

4. **Push to your fork**:
   ```bash
   git push origin your-feature-branch
   ```

5. **Create a Pull Request** on GitHub:
   - Provide a clear title and description
   - Reference any related issues
   - Describe what you changed and why
   - Include screenshots for UI changes
   - List any breaking changes

### Pull Request Checklist
- [ ] Code follows the project's style guidelines
- [ ] Tests have been added/updated
- [ ] All tests pass
- [ ] Documentation has been updated
- [ ] CHANGELOG.md has been updated (for user-facing changes)
- [ ] Commit messages are clear and descriptive
- [ ] No secrets or credentials are included

## Reporting Issues

### Bug Reports
When reporting bugs, please include:
- Description of the issue
- Steps to reproduce
- Expected behavior
- Actual behavior
- Environment details (OS, Python version, etc.)
- Log output or error messages
- Configuration details (sanitized, no secrets)

### Feature Requests
When requesting features, please include:
- Clear description of the feature
- Use case and motivation
- Examples of how it would work
- Any relevant references or examples

### Security Issues
Please report security vulnerabilities privately by emailing the maintainers. Do not create public issues for security problems.

## Questions?

If you have questions or need help, feel free to:
- Open an issue for discussion
- Check existing documentation in the `doc/` directory
- Review closed issues and PRs for similar questions

## License

By contributing to this project, you agree that your contributions will be licensed under the same license as the project.

---

Thank you for contributing to IMMICH ULTRA-SYNC! 🚀
