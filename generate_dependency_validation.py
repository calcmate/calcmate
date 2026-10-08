# -*- coding: utf-8 -*-
"""
CI용 Dependency Validation 스크립트
dependency-validation.json 생성
"""

import json
import subprocess
import sys


def get_installed_version(package_name):
    """설치된 패키지 버전 확인"""
    # Try to get version from package metadata first
    try:
        result = subprocess.run(
            [sys.executable, '-c', f'import {package_name}; print({package_name}.__version__ if hasattr({package_name}, "__version__") else "unknown")'],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            if version != "unknown":
                return version
    except Exception:
        pass
    
    # Fallback to pip show for packages without __version__
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'show', package_name],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if line.startswith('Version: '):
                    return line.split('Version: ')[1].strip()
    except Exception:
        pass
    
    return None


def validate_dependency(name, expected_version=None):
    """단일 의존성 검증"""
    version = get_installed_version(name)
    
    if version is None:
        return {
            "name": name,
            "requested_version": expected_version or "any",
            "installed_version": "NOT INSTALLED",
            "status": "FAIL",
            "error": f"Package {name} not installed"
        }
    
    if expected_version and version != expected_version:
        return {
            "name": name,
            "requested_version": expected_version,
            "installed_version": version,
            "status": "VERSION_MISMATCH",
            "warning": f"Expected {expected_version}, got {version}"
        }
    
    return {
        "name": name,
        "requested_version": expected_version or "any",
        "installed_version": version,
        "status": "PASS"
    }


def main():
    print("=" * 60)
    print("Dependency Validation")
    print("=" * 60)

    # 검증 대상 의존성들 (PoC OSS 포함)
    dependencies = [
        {"name": "formualizer", "expected": "0.10.1"},
        {"name": "mortgagemath", "expected": "0.7.1"},
        {"name": "pydantic", "expected": "2.13.4"},
        {"name": "pytest", "expected": None},
    ]

    results = []
    all_pass = True

    for dep in dependencies:
        print(f"\nValidating {dep['name']}...")
        result = validate_dependency(dep['name'], dep['expected'])
        results.append(result)
        
        if result['status'] == 'PASS':
            print(f"  OK {result['name']}: {result['installed_version']}")
        elif result['status'] == 'VERSION_MISMATCH':
            print(f"  WARNING {result['name']}: {result['warning']}")
            # Version mismatch는 FAIL이 아니라 경고로 처리
        else:
            print(f"  FAIL {result['name']}: {result.get('error', 'Unknown error')}")
            all_pass = False

    # 전체 상태 결정
    overall_status = "PASS" if all_pass else "FAIL"

    # 결과 구성
    validation_result = {
        "status": overall_status,
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "dependencies": results,
        "summary": {
            "total": len(results),
            "passed": sum(1 for r in results if r['status'] == 'PASS'),
            "version_mismatch": sum(1 for r in results if r['status'] == 'VERSION_MISMATCH'),
            "failed": sum(1 for r in results if r['status'] == 'FAIL'),
        }
    }

    # JSON 저장
    with open('dependency-validation.json', 'w', encoding='utf-8') as f:
        json.dump(validation_result, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print(f"Dependency Validation: {overall_status}")
    print(f"Total: {validation_result['summary']['total']}, "
          f"Passed: {validation_result['summary']['passed']}, "
          f"Version Mismatch: {validation_result['summary']['version_mismatch']}, "
          f"Failed: {validation_result['summary']['failed']}")
    print("dependency-validation.json 생성 완료")
    
    return overall_status == "PASS"


if __name__ == '__main__':
    import json
    success = main()
    exit(0 if success else 1)