#!/usr/bin/env python3
"""
Test Runner for TikTok/YouTube Transcription Service
Provides different test execution modes and comprehensive reporting.

Usage:
    python run_tests.py                    # Run all tests
    python run_tests.py --unit             # Run only unit tests
    python run_tests.py --integration      # Run only integration tests
    python run_tests.py --e2e              # Run only e2e tests
    python run_tests.py --fast             # Skip slow tests
    python run_tests.py --coverage         # Run with detailed coverage
    python run_tests.py --parallel         # Run tests in parallel
"""
import subprocess
import sys
import os
import argparse
from pathlib import Path

def run_command(cmd, description):
    """Run a command and handle errors"""
    print(f"\n🔄 {description}")
    print(f"Command: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print(f"✅ {description} completed successfully")
        if result.stdout:
            print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} failed")
        print(f"Error: {e}")
        if e.stdout:
            print(f"STDOUT: {e.stdout}")
        if e.stderr:
            print(f"STDERR: {e.stderr}")
        return False

def check_dependencies():
    """Check if test dependencies are installed"""
    print("🔍 Checking test dependencies...")
    
    try:
        import pytest
        import httpx
        import psycopg2
        print("✅ Core test dependencies are installed")
        return True
    except ImportError as e:
        print(f"❌ Missing test dependency: {e}")
        print("Run: pip install -r requirements-test.txt")
        return False

def setup_test_environment():
    """Set up environment variables for testing"""
    os.environ['TESTING'] = 'true'
    os.environ['LOG_LEVEL'] = 'INFO'
    os.environ['ENVIRONMENT'] = 'test'
    
    # Load environment variables from .env if it exists
    env_file = Path('.env')
    if env_file.exists():
        print("📄 Loading environment from .env file")
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            print("⚠️  python-dotenv not installed, skipping .env loading")
    
    print("🔧 Test environment configured")

def main():
    parser = argparse.ArgumentParser(description='Run tests for the transcription service')
    
    # Test selection
    parser.add_argument('--unit', action='store_true', help='Run only unit tests')
    parser.add_argument('--integration', action='store_true', help='Run only integration tests')
    parser.add_argument('--e2e', action='store_true', help='Run only end-to-end tests')
    parser.add_argument('--database', action='store_true', help='Run only database tests')
    parser.add_argument('--fts', action='store_true', help='Run only full-text search tests')
    parser.add_argument('--credits', action='store_true', help='Run only credit system tests')
    parser.add_argument('--sms', action='store_true', help='Run only SMS-related tests')
    
    # Test execution options
    parser.add_argument('--fast', action='store_true', help='Skip slow tests')
    parser.add_argument('--parallel', action='store_true', help='Run tests in parallel')
    parser.add_argument('--coverage', action='store_true', help='Generate detailed coverage report')
    parser.add_argument('--html-report', action='store_true', help='Generate HTML test report')
    parser.add_argument('--benchmark', action='store_true', help='Run performance benchmarks')
    
    # Debugging options
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--debug', action='store_true', help='Debug mode with extra logging')
    parser.add_argument('--pdb', action='store_true', help='Drop into debugger on failures')
    
    # Test file selection
    parser.add_argument('files', nargs='*', help='Specific test files to run')
    
    args = parser.parse_args()
    
    print("🧪 TikTok/YouTube Transcription Service Test Runner")
    print("=" * 60)
    
    # Check dependencies
    if not check_dependencies():
        sys.exit(1)
    
    # Setup environment
    setup_test_environment()
    
    # Build pytest command
    cmd = ['python', '-m', 'pytest']
    
    # Add markers based on test type selection
    markers = []
    if args.unit:
        markers.append('unit')
    if args.integration:
        markers.append('integration')
    if args.e2e:
        markers.append('e2e')
    if args.database:
        markers.append('database')
    if args.fts:
        markers.append('fts')
    if args.credits:
        markers.append('credits')
    if args.sms:
        markers.append('sms')
    
    if markers:
        cmd.extend(['-m', ' or '.join(markers)])
    
    # Skip slow tests if requested
    if args.fast:
        cmd.extend(['-m', 'not slow'])
    
    # Parallel execution
    if args.parallel:
        cmd.extend(['-n', 'auto'])
    
    # Coverage options
    if args.coverage:
        cmd.extend([
            '--cov=.',
            '--cov-report=term-missing',
            '--cov-report=html:htmlcov',
            '--cov-report=xml:coverage.xml',
            '--cov-fail-under=80'
        ])
    
    # HTML reporting
    if args.html_report:
        cmd.extend(['--html=reports/report.html', '--self-contained-html'])
        os.makedirs('reports', exist_ok=True)
    
    # Benchmark tests
    if args.benchmark:
        cmd.append('--benchmark-only')
    
    # Debug options
    if args.verbose:
        cmd.append('-v')
    if args.debug:
        cmd.extend(['--log-cli-level=DEBUG', '--capture=no'])
    if args.pdb:
        cmd.append('--pdb')
    
    # Add specific test files
    if args.files:
        cmd.extend(args.files)
    else:
        cmd.append('tests/')
    
    # Run the tests
    success = run_command(cmd, "Running test suite")
    
    if success:
        print("\n🎉 All tests passed!")
        
        # Show coverage summary if coverage was run
        if args.coverage:
            print("\n📊 Coverage report generated:")
            print("  - Terminal: see output above")
            print("  - HTML: open htmlcov/index.html")
            print("  - XML: coverage.xml")
        
        # Show HTML report location
        if args.html_report:
            print("\n📋 HTML test report: reports/report.html")
        
        print("\n🚀 Ready to ship with confidence!")
        
    else:
        print("\n💥 Some tests failed!")
        print("\nNext steps:")
        print("  1. Review the test output above")
        print("  2. Fix any failing tests")
        print("  3. Run tests again")
        sys.exit(1)

if __name__ == '__main__':
    main()