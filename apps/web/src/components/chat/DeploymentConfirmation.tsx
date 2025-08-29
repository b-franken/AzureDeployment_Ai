"use client"

import { useState } from "react"
import { AlertCircle, CheckCircle, Clock, DollarSign, MapPin, Server } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"

type DeploymentPreview = {
    resourceType: string
    resourceName: string
    resourceGroup: string
    location: string
    environment: string
    monthlyCost: number
    deploymentId: string
    expiresAt: string
}

type DeploymentConfirmationProps = {
    preview: DeploymentPreview
    onConfirm: () => void
    onCancel: () => void
    isConfirming: boolean
}

export default function DeploymentConfirmation({
    preview,
    onConfirm,
    onCancel,
    isConfirming
}: DeploymentConfirmationProps) {
    const [acknowledged, setAcknowledged] = useState(false)
    
    const expiryTime = new Date(preview.expiresAt).toLocaleTimeString()
    const costColor = preview.monthlyCost === 0 
        ? "text-green-600" 
        : preview.monthlyCost < 10 
            ? "text-yellow-600" 
            : "text-red-600"

    return (
        <Card className="border-blue-200 bg-blue-50 shadow-lg">
            <CardHeader>
                <div className="flex items-center gap-2">
                    <AlertCircle className="h-5 w-5 text-blue-600" />
                    <CardTitle className="text-lg">Confirm Azure Deployment</CardTitle>
                </div>
                <CardDescription>
                    Review the deployment details below and confirm to proceed with resource creation.
                </CardDescription>
            </CardHeader>
            
            <CardContent className="space-y-4">
                {/* Resource Summary */}
                <div className="grid grid-cols-2 gap-4">
                    <div className="flex items-center gap-2">
                        <Server className="h-4 w-4 text-gray-600" />
                        <div>
                            <p className="text-sm font-medium">{preview.resourceType}</p>
                            <p className="text-xs text-gray-600">{preview.resourceName}</p>
                        </div>
                    </div>
                    
                    <div className="flex items-center gap-2">
                        <MapPin className="h-4 w-4 text-gray-600" />
                        <div>
                            <p className="text-sm font-medium">{preview.location}</p>
                            <p className="text-xs text-gray-600">{preview.resourceGroup}</p>
                        </div>
                    </div>
                </div>

                <Separator />

                {/* Cost Information */}
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                        <DollarSign className="h-4 w-4 text-gray-600" />
                        <span className="text-sm font-medium">Estimated Monthly Cost</span>
                    </div>
                    <Badge variant="outline" className={`${costColor} border-current`}>
                        ${preview.monthlyCost.toFixed(2)} USD/month
                    </Badge>
                </div>

                {/* Session Information */}
                <div className="flex items-center justify-between text-xs text-gray-600">
                    <div className="flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        <span>Preview expires at {expiryTime}</span>
                    </div>
                    <Badge variant="secondary" className="text-xs">
                        {preview.environment.toUpperCase()}
                    </Badge>
                </div>

                <Separator />

                {/* Acknowledgment */}
                <div className="flex items-start gap-2">
                    <input
                        type="checkbox"
                        id="acknowledge"
                        checked={acknowledged}
                        onChange={(e) => setAcknowledged(e.target.checked)}
                        className="mt-1"
                    />
                    <label htmlFor="acknowledge" className="text-sm text-gray-700">
                        I acknowledge that this deployment will create Azure resources and may incur costs.
                        I have reviewed the Bicep and Terraform templates above.
                    </label>
                </div>

                {/* Action Buttons */}
                <div className="flex gap-3 pt-2">
                    <Button
                        onClick={onConfirm}
                        disabled={!acknowledged || isConfirming}
                        className="flex-1 bg-blue-600 hover:bg-blue-700"
                    >
                        {isConfirming ? (
                            <>
                                <div className="mr-2 h-4 w-4 animate-spin rounded-full border-2 border-white border-r-transparent" />
                                Deploying...
                            </>
                        ) : (
                            <>
                                <CheckCircle className="mr-2 h-4 w-4" />
                                Deploy Resources
                            </>
                        )}
                    </Button>
                    
                    <Button
                        variant="outline"
                        onClick={onCancel}
                        disabled={isConfirming}
                        className="flex-1"
                    >
                        Cancel
                    </Button>
                </div>

                {/* Security Notice */}
                <div className="rounded-lg bg-yellow-50 border border-yellow-200 p-3">
                    <p className="text-xs text-yellow-800">
                        <strong>Security Notice:</strong> This preview session will expire in 30 minutes. 
                        All resources will be deployed to the {preview.environment} environment using Azure best practices.
                    </p>
                </div>
            </CardContent>
        </Card>
    )
}