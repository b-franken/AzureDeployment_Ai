from __future__ import annotations


def provide_helpful_suggestions(original_input: str) -> list[str]:
    suggestions: list[str] = []
    t = original_input.lower()

    if "storage" in t:
        suggestions.append(
            "create storage account myapp123 in westeurope resource group myapp-dev-rg"
        )
        suggestions.append("create storage mydata in eastus with sku Standard_GRS")

    if "web" in t or "app" in t:
        suggestions.append("create web app mywebapp in westeurope resource group myapp-dev-rg")
        suggestions.append("create webapp mysite with runtime python|3.9")

    if "kubernetes" in t or "aks" in t:
        suggestions.append("create aks cluster mycluster in westeurope resource group myapp-dev-rg")
        suggestions.append("create kubernetes myk8s with 3 nodes")

    if not suggestions:
        suggestions.extend(
            [
                "create resource group myproject-dev-rg in westeurope",
                "create storage account mydata123 in westeurope",
                "create web app mywebapp in westeurope",
                "create aks cluster mycluster in westeurope",
            ]
        )
    return suggestions
