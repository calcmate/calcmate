#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
JUnit XML Merge Script
Merges multiple JUnit XML test result files into a single testsuites file.
"""

import xml.etree.ElementTree as ET
import os
import sys


def main():
    xml_files = [
        "test-results-factory.xml",
        "test-results-loan.xml",
        "test-results-existing.xml",
    ]

    testsuite_root = ET.Element("testsuites")
    total_tests = 0
    total_failures = 0
    total_errors = 0
    total_skipped = 0
    total_time = 0.0

    for xml_file in xml_files:
        if os.path.exists(xml_file):
            tree = ET.parse(xml_file)
            root = tree.getroot()
            if root.tag == "testsuite":
                suites = [root]
            else:
                suites = list(root)
            for suite in suites:
                total_tests += int(suite.get("tests", 0))
                total_failures += int(suite.get("failures", 0))
                total_errors += int(suite.get("errors", 0))
                total_skipped += int(suite.get("skipped", 0))
                total_time += float(suite.get("time", 0))
                testsuite_root.append(suite)

    merged_root = ET.Element("testsuites")
    merged_root.set("tests", str(total_tests))
    merged_root.set("failures", str(total_failures))
    merged_root.set("errors", str(total_errors))
    merged_root.set("skipped", str(total_skipped))
    merged_root.set("time", str(total_time))

    for child in testsuite_root:
        merged_root.append(child)

    ET.ElementTree(merged_root).write("test-results.xml", encoding="utf-8", xml_declaration=True)
    print("Merged: tests={}, failures={}, errors={}, skipped={}".format(total_tests, total_failures, total_errors, total_skipped))
    return 0


if __name__ == "__main__":
    sys.exit(main())