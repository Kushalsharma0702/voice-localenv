"""
Exotel Service Module
Provides a centralized, robust service for all Exotel API interactions.
"""
import os
import httpx
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth
from utils.logger import logger

load_dotenv()

class ExotelService:
    """
    A centralized service for handling all Exotel API interactions.
    """
    def __init__(self):
        """
        Initializes the Exotel service with credentials from environment variables.
        """
        self.sid = os.getenv("EXOTEL_SID")
        self.api_key = os.getenv("EXOTEL_API_KEY")
        self.api_token = os.getenv("EXOTEL_TOKEN")
        self.virtual_number = os.getenv("EXOTEL_VIRTUAL_NUMBER")
        self.app_id = os.getenv("EXOTEL_FLOW_APP_ID")
        
        if not all([self.sid, self.api_key, self.api_token, self.virtual_number, self.app_id]):
            logger.critical("Exotel credentials are not fully configured in .env file.")
            raise ValueError("Exotel credentials are not fully configured.")

        self.base_url = f"https://{self.api_key}:{self.api_token}@api.exotel.com/v1/Accounts/{self.sid}"

    async def make_call(self, from_number: str, to_number: str, caller_id: str, url: str = None, flow_id: str = None):
        """
        Makes a call through the Exotel API.

        Args:
            from_number (str): The number to connect.
            to_number (str): The destination number.
            caller_id (str): The caller ID to display.
            url (str, optional): The URL for connect call. Defaults to None.
            flow_id (str, optional): The App/Flow ID for the call. Defaults to None.

        Returns:
            dict: The JSON response from Exotel, or None if the call fails.
        """
        if url:
            endpoint = url
            payload = {
                "From": from_number,
                "To": to_number,
                "CallerId": caller_id,
            }
        elif flow_id:
            endpoint = f"{self.base_url}/Calls/connect_flow.json"
            payload = {
                "From": from_number,
                "To": to_number,
                "CallerId": caller_id,
                "FlowId": flow_id
            }
        else:
            logger.error("Either 'url' for connect call or 'flow_id' for flow call must be provided.")
            return None

        logger.info(f"Initiating Exotel call to {to_number} from {from_number} using caller ID {caller_id}")

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(endpoint, data=payload)
                response.raise_for_status()
                logger.info(f"Exotel API call successful. Response: {response.text}")
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error occurred: {e.response.status_code} - {e.response.text}")
                return None
            except httpx.RequestError as e:
                logger.error(f"Request to Exotel API failed: {e}")
                return None
            except Exception as e:
                logger.error(f"An unexpected error occurred during Exotel call: {e}")
                return None

    async def trigger_customer_call(self, customer_number: str):
        """
        Triggers a call to a customer and connects them to a pre-defined Exotel flow.
        """
        logger.info(f"Triggering call to customer: {customer_number}")
        return await self.make_call(
            from_number=customer_number,
            to_number=self.virtual_number,
            caller_id=self.virtual_number,
            flow_id=self.app_id
        )

    async def trigger_agent_transfer(self, customer_number: str, agent_number: str):
        """
        Triggers a call to connect a customer with an agent.
        """
        logger.info(f"Triggering agent transfer for customer {customer_number} to agent {agent_number}")
        connect_url = f"{self.base_url}/Calls/connect.json"
        return await self.make_call(
            from_number=customer_number,
            to_number=agent_number,
            caller_id=self.virtual_number,
            url=connect_url
        )

# Singleton instance
exotel_service = ExotelService()
