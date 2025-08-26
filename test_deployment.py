#!/usr/bin/env python3
"""
Test script for Azure deployment functionality
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from app.tools.azure.tool import AzureProvision

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_deployment():
    """Test the Azure deployment tool with dry_run=False (preview mode)"""
    tool = AzureProvision()
    
    # Test parameters for creating a resource group
    test_params = {
        "action": "create resource group test-123 in westeurope",
        "resource_group": "test-123",
        "location": "westeurope",
        "subscription_id": "2d4408a0-2043-4c59-be4e-3b3fdc4d2130",
        "environment": "dev",
        "dry_run": True  # This should trigger preview mode with Bicep/Terraform code
    }
    
    print("Testing Azure deployment tool...")
    print(f"Parameters: {test_params}")
    print("-" * 80)
    
    try:
        result = await tool.run(**test_params)
        
        print("Tool execution completed!")
        print(f"Result OK: {result['ok']}")
        print(f"Summary: {result['summary']}")
        print()
        
        if isinstance(result['output'], str):
            # If output is a string, try to parse it as JSON for better display
            import json
            try:
                output_data = json.loads(result['output'])
                print("Deployment Details:")
                print(f"  Deployment ID: {output_data.get('deployment_id', 'N/A')}")
                print(f"  Action: {output_data.get('action', 'N/A')}")
                print(f"  Status: {output_data.get('status', 'N/A')}")
                print()
                
                if 'infrastructure_code' in output_data:
                    print("Infrastructure as Code Generated:")
                    
                    bicep = output_data['infrastructure_code'].get('bicep', '')
                    if bicep:
                        print("\nBicep Code:")
                        print("```bicep")
                        print(bicep[:500] + "..." if len(bicep) > 500 else bicep)
                        print("```")
                    
                    terraform = output_data['infrastructure_code'].get('terraform', '')
                    if terraform:
                        print("\nTerraform Code:")
                        print("```hcl")
                        print(terraform[:500] + "..." if len(terraform) > 500 else terraform)
                        print("```")
                
                if 'resource_details' in output_data:
                    print("\nResource Details:")
                    for key, value in output_data['resource_details'].items():
                        print(f"  {key}: {value}")
                
                if 'cost_estimate' in output_data:
                    print("\nCost Estimate:")
                    cost = output_data['cost_estimate']
                    if isinstance(cost, dict):
                        for key, value in cost.items():
                            print(f"  {key}: {value}")
                    else:
                        print(f"  {cost}")
                        
            except json.JSONDecodeError:
                print("Raw Output:")
                print(result['output'])
        else:
            print("Output (structured):")
            print(result['output'])
            
    except Exception as e:
        print(f"Error during tool execution: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_deployment())