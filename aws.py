import boto3
import json
import zipfile
import os
import dotenv
dotenv.load_dotenv('.env')

AWS_REGION = 'us-east-1'
DEFAULT_DB_INSTANCE_CLASS = 'db.t2.micro'
DEFAULT_DB_STORAGE = 20
DEFAULT_TAG = 'gpt-experiment'
AWS_ACCOUNT_ID = os.getenv('AWS_ACCOUNT_ID')
assert AWS_ACCOUNT_ID is not None, "Please set your AWS_ACCOUNT_ID in .env file"
AWS_LAMBDA_ROLE = f'arn:aws:iam::{AWS_ACCOUNT_ID}:role/lambda_api_gateway_role'
api_client = boto3.client('apigateway')
lambda_client = boto3.client('lambda')
cognito_client = boto3.client('cognito-idp')


def create_new_api(name: str, description: str):
    """Creates a new API Gateway API"""
    response = api_client.create_rest_api(
        name=name,
        description=description,
        tags={
            'resource_owner': DEFAULT_TAG
        }
    )
    # Add authentication
    authentication = add_authentication(response['id'])
    return json.dumps({
        "success": True,
        "api_id": response['id'],
        "authentication": authentication
    })


def create_new_api_endpoint(
    api_id: str,
    endpoint: str,
    method: str,
    code: str,
    authorizer_id: str | None,
    runtime: str = 'nodejs18.x'
):
    """Creates a new API Gateway API endpoint"""
    # Get the resources from the endpoint
    resources = endpoint.split('/')
    # Only keep the resources that are not empty strings
    resources = [resource for resource in resources if resource != '']
    # Get the parent resource
    parent_id = None
    resource_id = None
    api_resources_response = api_client.get_resources(
        restApiId=api_id
    )
    api_resources = api_resources_response['items']
    resource = resources[-1]  # The last resource is the one we want to create
    if len(resources) > 1:
        # Get the parent resource
        parent_resource = resources[-2]
        parent_resource = next(
            (resource for resource in api_resources if resource['pathPart'] == parent_resource), None)
        parent_id = parent_resource['id']

    if parent_id is None:
        # Use the root resource for all, this assumes the endpoint is not nested
        parent_id = api_resources_response['items'][0]['id']

    resource_id = create_resource(api_id, parent_id, resource)

    # Create a method
    create_resource_method(api_id, resource_id, method)
    # Create a Lambda function
    endpoint_name = endpoint.replace('/', '-')
    function_name = f'{api_id}-{endpoint_name}'
    lambda_response = create_endpoint_function(
        function_name=function_name, code=code, runtime=runtime)
    # Add the Lambda function to the method
    lambda_arn = lambda_response['FunctionArn']

    if authorizer_id:
        # Add the authorizer to the method
        try:
            api_client.update_method(
                restApiId=api_id,
                resourceId=resource_id,
                httpMethod=method,
                patchOperations=[
                    {
                        'op': 'replace',
                        'path': '/authorizationType',
                        'value': 'COGNITO_USER_POOLS'
                    },
                    {
                        'op': 'replace',
                        'path': '/authorizerId',
                        'value': authorizer_id
                    }
                ]
            )
        except Exception as e:
            print('Error adding authorizer to method')
            print(f'api_id: {api_id}')
            print(f'resource_id: {resource_id}')
            print(f'method: {method}')
            print(f'authorizer_id: {authorizer_id}')
            print(f'Error: {e}')

    # Give API Gateway permission to invoke the Lambda function
    lambda_client.add_permission(
        FunctionName=function_name,
        Action='lambda:InvokeFunction',
        Principal='apigateway.amazonaws.com',
        SourceArn=f'arn:aws:execute-api:{AWS_REGION}:{AWS_ACCOUNT_ID}:{api_id}/*',
        StatementId=f'api-gateway-invoke-{function_name}'
    )

    api_client.put_integration(
        restApiId=api_id,
        resourceId=resource_id,
        httpMethod=method,
        type='AWS_PROXY',
        integrationHttpMethod=method,
        uri=f'arn:aws:apigateway:{AWS_REGION}:lambda:path/2015-03-31/functions/{lambda_arn}/invocations',
    )
    # Deploy the API
    api_client.create_deployment(
        restApiId=api_id,
        stageName='prod',
    )
    # Return the endpoint URL
    return json.dumps({
        "success": True,
        "endpoint_url": 'https://{api_id}.execute-api.{AWS_REGION}.amazonaws.com/prod{endpoint}'
    })


def create_resource(api_id: str, parent_id: str | None, path_part: str):
    """Create a resource in an API Gateway API for a given path part"""
    response = api_client.create_resource(
        restApiId=api_id,
        parentId=parent_id,
        pathPart=path_part,
    )
    return response['id']


def create_resource_method(api_id: str, resource_id: str | None, method: str = 'GET'):
    method_response = api_client.put_method(
        restApiId=api_id,
        resourceId=resource_id,
        httpMethod=method,
        authorizationType='NONE',  # TODO: Change this
    )
    return method_response


def create_endpoint_function(
    function_name: str,
    code: str,
    runtime: str,
):
    """Creates a Lambda function and adds it to the API Gateway API for a given endpoint"""
    # Create a file to upload to Lambda
    filename = 'lambda_function.js'
    if runtime == 'nodejs18.x' or runtime == 'nodejs14.x' or runtime == 'nodejs16.x':
        filename = 'lambda_function.js'
    elif runtime == 'python3.8' or runtime == 'python3.9' or runtime == 'python3.10':
        filename = 'lambda_function.py'
    elif runtime == 'java17' or runtime == 'java8' or runtime == 'java8.al2' or runtime == 'java11':
        filename = 'lambda_function.java'
    elif runtime == 'go1.x':
        filename = 'lambda_function.go'
    elif runtime == 'ruby2.7' or runtime == 'ruby3.2':
        filename = 'lambda_function.rb'
    elif runtime == 'dotnet6':
        filename = 'lambda_function.cs'
    elif runtime == 'provided' or runtime == 'provided.al2':
        filename = 'lambda_function'
    with open(filename, 'w') as f:
        f.write(code)

    # Create a zip file
    with zipfile.ZipFile('lambda_function.zip', 'w') as z:
        z.write(filename)

    # Create the Lambda function
    handler = 'lambda_function.handler'
    lambda_response = lambda_client.create_function(
        FunctionName=function_name,
        Runtime=runtime,
        Role=AWS_LAMBDA_ROLE,
        Handler=handler,
        Code={
            'ZipFile': open('lambda_function.zip', 'rb').read()
        },
        Tags={
            'resource_owner': DEFAULT_TAG
        }
    )

    # Delete the zip file
    os.remove(filename)
    os.remove('lambda_function.zip')
    return lambda_response


def add_authentication(api_id: str):
    """Add authentication to an API Gateway API"""
    # Create a Cognito user pool
    pool_name = f'api-{api_id}-user-pool'
    client_name = f'api-{api_id}-user-pool-client'
    redirect_uri = f'https://{api_id}.execute-api.{AWS_REGION}.amazonaws.com/prod/authenticate'
    return create_user_pool(
        api_id, pool_name, client_name, redirect_uri)


def create_user_pool(api_id, pool_name, client_name, redirect_uri):
    # Create a new Cognito user pool
    response = cognito_client.create_user_pool(
        PoolName=pool_name,
        AutoVerifiedAttributes=['email'],
        Policies={
            'PasswordPolicy': {
                'MinimumLength': 8,
                'RequireLowercase': False,
                'RequireUppercase': False,
                'RequireNumbers': False,
                'RequireSymbols': False,
            }
        },
        EmailVerificationSubject='Verify your email for our app',
        EmailVerificationMessage='Please click the link below to verify your email address: {####}',
        Schema=[
            {
                'Name': 'email',
                'AttributeDataType': 'String',
                'Mutable': False,
                'Required': True
            }
        ],
        UserPoolTags={
            'api_id': api_id,
            'resource_owner': DEFAULT_TAG
        }
    )
    user_pool_id = response['UserPool']['Id']

    # Create a new Cognito user pool client
    response = cognito_client.create_user_pool_client(
        UserPoolId=user_pool_id,
        ClientName=client_name,
        GenerateSecret=False,
        ExplicitAuthFlows=['ALLOW_USER_PASSWORD_AUTH',
                           'ALLOW_REFRESH_TOKEN_AUTH'],
        CallbackURLs=[redirect_uri],
        LogoutURLs=[redirect_uri],
        SupportedIdentityProviders=['COGNITO'],
        AllowedOAuthFlows=['code'],
        AllowedOAuthScopes=['openid']
    )
    user_pool_client_id = response['UserPoolClient']['ClientId']

    # Attach the Cognito user pool to the API Gateway
    response = api_client.create_authorizer(
        restApiId=api_id,
        name='cognito_authorizer',
        type='COGNITO_USER_POOLS',
        providerARNs=[
            f'arn:aws:cognito-idp:{AWS_REGION}:{AWS_ACCOUNT_ID}:userpool/{user_pool_id}'],
        identitySource='method.request.header.Authorization',
        authorizerResultTtlInSeconds=300
    )
    authorizer_id = response['id']
    return {
        "success": True,
        "user_pool_id": user_pool_id,
        "user_pool_client_id": user_pool_client_id,
        "authorizer_id": authorizer_id
    }
