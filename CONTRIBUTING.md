# Contributing to IMMICH ULTRA-SYNC

Thank you for considering contributing to IMMICH ULTRA-SYNC! We welcome contributions from the community to help improve this project.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [How Can I Contribute?](#how-can-i-contribute)
- [Development Setup](#development-setup)
- [Pull Request Process](#pull-request-process)
- [Coding Standards](#coding-standards)
- [Testing](#testing)
- [Documentation](#documentation)

## Code of Conduct

This project follows a code of conduct to foster an open and welcoming environment. Be respectful, considerate, and constructive in all interactions.

## How Can I Contribute?

### Reporting Bugs

Before creating bug reports, please check existing issues to avoid duplicates. When creating a bug report, include:

- A clear, descriptive title
- Detailed steps to reproduce the issue
- Expected vs. actual behavior
- Your environment (OS, Python version, ExifTool version)
- Relevant logs or error messages

### Suggesting Enhancements

Enhancement suggestions are welcome! Please provide:

- A clear description of the enhancement
- Use cases and benefits
- Potential implementation approach (if applicable)

### Code Contributions

1. **Fork the repository** and create a new branch from `main`
2. **Make your changes** following our coding standards
3. **Add tests** for new functionality
4. **Update documentation** as needed
5. **Submit a pull request**

## Development Setup

### Prerequisites

- Python 3.9 or higher
- ExifTool installed on your system
- Git for version control

### Local Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/germanlion67/immich-metadata-sync.git
   cd immich-metadata-sync
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Verify ExifTool installation:
   ```bash
   exiftool -ver
   ```

### Running the Project Locally

To run the sync script locally:

```bash
python3 script/immich-ultra-sync.py --all --dry-run
```

Make sure to set up your environment variables or configuration file with valid Immich credentials.

## Pull Request Process

1. **Update documentation** - Ensure README.md, CHANGELOG.md, and any relevant docs are updated
2. **Add tests** - New features should include unit tests
3. **Run tests** - Ensure all tests pass before submitting
4. **Follow commit conventions** - Use clear, descriptive commit messages
5. **Keep changes focused** - One feature or fix per PR
6. **Update CHANGELOG.md** - Add an entry under "Unreleased" section

### PR Checklist

- [ ] Tests pass locally
- [ ] Code follows project style guidelines
- [ ] Documentation is updated
- [ ] CHANGELOG.md is updated
- [ ] Commit messages are clear and descriptive
- [ ] PR description explains the changes and motivation

## Coding Standards

### Python Style

- Follow [PEP 8](https://pep8.org/) style guidelines
- Use meaningful variable and function names
- Add docstrings for modules, classes, and functions
- Keep functions focused and concise
- Use type hints where appropriate

### Code Organization

The project follows a modular structure:

```
script/
├── immich-ultra-sync.py  # Main orchestration script
├── utils.py              # Utility functions and constants
├── api.py                # API-related functions
└── exif.py               # EXIF/XMP metadata handling
```

When adding new features:
- Place utility functions in `utils.py`
- API-related code goes in `api.py`
- EXIF/XMP logic belongs in `exif.py`
- Keep the main script focused on orchestration

### Security Considerations

- Never commit API keys, passwords, or sensitive data
- Validate and sanitize all user inputs
- Use path validation to prevent directory traversal
- Follow principle of least privilege

## Testing

### Running Tests

Run the test suite using pytest:

```bash
pytest tests/ -v
```

Or using unittest:

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

### Writing Tests

- Place tests in the `tests/` directory
- Name test files with `test_` prefix
- Use descriptive test function names
- Include both positive and negative test cases
- Mock external dependencies (API calls, file I/O)

Example test structure:

```python
import unittest
from script import utils

class TestUtilityFunction(unittest.TestCase):
    def test_valid_input(self):
        result = utils.some_function("valid_input")
        self.assertEqual(result, expected_value)
    
    def test_invalid_input(self):
        with self.assertRaises(ValueError):
            utils.some_function("invalid_input")
```

## Documentation

### Code Documentation

- Add docstrings to all public functions and classes
- Use clear, concise language
- Include parameter descriptions and return types
- Provide usage examples for complex functions

### User Documentation

When adding features that affect users:

- Update README.md with new flags/options
- Add examples to demonstrate usage
- Update relevant documentation in `doc/` directory
- Consider adding entries to both English and German docs

### Changelog

Update CHANGELOG.md for all user-facing changes:

```markdown
## [Unreleased]

### Added
- New feature description

### Changed
- Modified behavior description

### Fixed
- Bug fix description
```

## Questions?

If you have questions or need help:

- Check existing issues and documentation
- Create a new issue with the `question` label
- Reach out to maintainers

Thank you for contributing to IMMICH ULTRA-SYNC! 🎉
